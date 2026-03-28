from calendar import monthrange

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.aws.client import AwsConnector
from app.core.config import get_settings
from app.models import Anomaly, CostRecord, Recommendation, ResourceSnapshot
from app.schemas.api import (
    AnomalyResponse,
    AnomalyStatusPoint,
    AnomalyStatusResponse,
    DashboardSummaryResponse,
    NativeSignalStatusResponse,
    OptimizationExecutionResponse,
    OptimizationRequest,
    RecommendationResponse,
    SyncResponse,
)
from app.services.anomaly_detection import AnomalyDetectionService
from app.services.alerts import AlertService
from app.services.ingestion import IngestionService
from app.services.job_monitor import JobMonitorService
from app.services.optimization import OptimizationService
from app.services.recommendations import RecommendationService
from app.services.runtime_settings import RuntimeSettingsService


class CostIntelligenceService:
    COST_SIGNAL_EPSILON = 0.005

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.runtime_settings = RuntimeSettingsService(db)

    def sync(self) -> SyncResponse:
        ingested_cost_records, ingested_resource_snapshots = IngestionService(self.db).ingest()
        anomalies_detected = AnomalyDetectionService(self.db).run()
        recommendations_generated = RecommendationService(self.db).generate()
        if anomalies_detected and self.settings.alert_on_anomaly_detected:
            AlertService().send(
                "anomalies_detected",
                "warning",
                {
                    "anomalies_detected": anomalies_detected,
                    "recommendations_generated": recommendations_generated,
                    "data_mode": self.runtime_settings.get_data_mode(),
                },
            )
        return SyncResponse(
            ingested_cost_records=ingested_cost_records,
            ingested_resource_snapshots=ingested_resource_snapshots,
            anomalies_detected=anomalies_detected,
            recommendations_generated=recommendations_generated,
        )

    def list_anomalies(self) -> list[AnomalyResponse]:
        rows = self.db.execute(select(Anomaly).order_by(Anomaly.detected_at.desc())).scalars().all()
        return [AnomalyResponse.model_validate(row) for row in rows]

    def list_recommendations(self) -> list[RecommendationResponse]:
        rows = self.db.execute(select(Recommendation).order_by(Recommendation.created_at.desc())).scalars().all()
        return [RecommendationResponse.model_validate(row) for row in rows]

    def get_anomaly_status(self) -> AnomalyStatusResponse:
        rows = self.db.execute(
            select(
                CostRecord.usage_date,
                func.count(CostRecord.id),
                func.coalesce(func.sum(CostRecord.cost_amount), 0.0),
            )
            .group_by(CostRecord.usage_date)
            .order_by(CostRecord.usage_date.asc())
        ).all()
        points = [
            AnomalyStatusPoint(
                usage_date=row[0].isoformat(),
                record_count=int(row[1]),
                total_cost=self._normalize_cost(float(row[2])),
                point_source=self._point_source_label(),
            )
            for row in rows
        ]
        observed_days = len(points)
        signal_days = sum(1 for point in points if abs(point.total_cost) >= self.COST_SIGNAL_EPSILON)
        min_days_required = 7
        latest_detection_run_at = self.db.execute(select(func.max(Anomaly.detected_at))).scalar_one()
        timeline_mode = self._timeline_mode()
        sync_markers = [
            {
                "started_at": run.started_at,
                "status": run.status,
                "records_ingested": int((run.details_json or {}).get("ingested_cost_records", 0)),
                "anomalies_detected": int((run.details_json or {}).get("anomalies_detected", 0)),
            }
            for run in JobMonitorService(self.db).latest(limit=8)
            if run.job_name == "cloud-cost-sync"
        ]

        if observed_days == 0:
            readiness = "waiting_for_billing_history"
            status_message = "AWS billing history is not available yet, so the ML detector has nothing real to analyze."
        elif signal_days == 0:
            readiness = "waiting_for_cost_signal"
            status_message = (
                "Billing rows are arriving, but real billed spend is still zero or near zero, so anomaly ML is waiting "
                "for usable cost signal."
            )
        elif signal_days < min_days_required:
            readiness = "warming_up"
            status_message = (
                f"ML anomaly detection is warming up with {signal_days} of {min_days_required} required non-zero billing days."
            )
        else:
            readiness = "ready"
            status_message = (
                f"ML anomaly detection is ready with {signal_days} billed days available for baseline analysis."
            )

        return AnomalyStatusResponse(
            readiness=readiness,
            status_message=status_message,
            min_days_required=min_days_required,
            observed_days=observed_days,
            signal_days=signal_days,
            latest_detection_run_at=latest_detection_run_at,
            timeline_mode=timeline_mode,
            points=points,
            sync_markers=sync_markers,
        )

    def get_dashboard_summary(self) -> DashboardSummaryResponse:
        actual_billed_cost = self._normalize_cost(
            self.db.execute(select(func.coalesce(func.sum(CostRecord.cost_amount), 0.0))).scalar_one()
        )
        estimated_run_rate = self._normalize_cost(
            self.db.execute(select(func.coalesce(func.sum(ResourceSnapshot.monthly_cost_estimate), 0.0))).scalar_one()
        )
        cost_rows = self.db.execute(
            select(CostRecord.usage_date, func.coalesce(func.sum(CostRecord.cost_amount), 0.0))
            .group_by(CostRecord.usage_date)
            .order_by(CostRecord.usage_date.asc())
        ).all()
        signal_days = sum(
            1 for _, amount in cost_rows if abs(self._normalize_cost(float(amount or 0.0))) >= self.COST_SIGNAL_EPSILON
        )
        latest_usage_date = cost_rows[-1][0] if cost_rows else None
        projected_end_of_month_cost = estimated_run_rate
        has_actual_cost = abs(actual_billed_cost) >= self.COST_SIGNAL_EPSILON

        if has_actual_cost and latest_usage_date is not None:
            days_in_month = monthrange(latest_usage_date.year, latest_usage_date.month)[1]
            observed_day = max(latest_usage_date.day, 1)
            projected_end_of_month_cost = self._normalize_cost((actual_billed_cost / observed_day) * days_in_month)

        anomaly_count = self.db.execute(select(func.count(Anomaly.id))).scalar_one()
        recommendation_count = self.db.execute(select(func.count(Recommendation.id))).scalar_one()
        estimated_monthly_savings = self.db.execute(
            select(func.coalesce(func.sum(Recommendation.estimated_monthly_savings), 0.0))
        ).scalar_one()
        last_cost_sync = self.db.execute(select(func.max(CostRecord.created_at))).scalar_one()
        last_snapshot_sync = self.db.execute(select(func.max(ResourceSnapshot.captured_at))).scalar_one()
        last_sync_at = max([value for value in [last_cost_sync, last_snapshot_sync] if value is not None], default=None)

        if not cost_rows:
            billing_signal_status = "no_billing_records"
            cost_source = "no_billing_records"
        elif has_actual_cost:
            billing_signal_status = "actual_billing_available"
            cost_source = "actual_billing"
        else:
            billing_signal_status = "billing_zero_or_credit_only"
            cost_source = "inventory_estimate"

        return DashboardSummaryResponse(
            total_cost=actual_billed_cost,
            actual_billed_cost=actual_billed_cost,
            estimated_monthly_run_rate=estimated_run_rate,
            projected_end_of_month_cost=self._normalize_cost(float(projected_end_of_month_cost)),
            cost_source=cost_source,
            billing_signal_status=billing_signal_status,
            has_actual_billing_data=has_actual_cost,
            signal_days=signal_days,
            data_mode=self.runtime_settings.get_data_mode(),
            anomaly_count=int(anomaly_count),
            recommendation_count=int(recommendation_count),
            estimated_monthly_savings=float(estimated_monthly_savings),
            last_sync_at=last_sync_at,
        )

    def execute_recommendations(
        self,
        request: OptimizationRequest,
    ) -> list[OptimizationExecutionResponse]:
        return OptimizationService(self.db).execute(request)

    def get_native_signal_status(self) -> NativeSignalStatusResponse:
        mode = self.runtime_settings.get_data_mode()
        if mode == "demo" or not self.settings.aws_enabled:
            return NativeSignalStatusResponse(
                provider="aws",
                anomaly_monitor_count=0,
                active_native_anomaly_count=0,
                budget_count=0,
                budget_alert_count=0,
                compute_optimizer_status="Disabled",
                trusted_advisor_available=False,
            )
        try:
            status = AwsConnector().fetch_native_signal_status(self.settings.ingestion_lookback_days)
        except Exception:
            status = {
                "provider": "aws",
                "anomaly_monitor_count": 0,
                "active_native_anomaly_count": 0,
                "budget_count": 0,
                "budget_alert_count": 0,
                "compute_optimizer_status": "Unavailable",
                "trusted_advisor_available": False,
            }
        return NativeSignalStatusResponse(**status)

    def _timeline_mode(self) -> str:
        mode = self.runtime_settings.get_data_mode()
        has_demo_points = self.db.execute(
            select(func.count(CostRecord.id)).where(CostRecord.provider == "demo")
        ).scalar_one()
        if mode == "demo" or (mode == "hybrid" and int(has_demo_points) > 0):
            return "demo_preset" if mode == "demo" else "hybrid_timeline"
        return "live_timeline"

    def _point_source_label(self) -> str:
        mode = self.runtime_settings.get_data_mode()
        if mode == "demo":
            return "demo"
        if mode == "hybrid":
            return "hybrid"
        return "live"

    def _normalize_cost(self, value: float) -> float:
        amount = float(value or 0.0)
        if abs(amount) < self.COST_SIGNAL_EPSILON:
            return 0.0
        return amount
