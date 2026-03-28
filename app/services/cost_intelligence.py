from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Anomaly, CostRecord, Recommendation, ResourceSnapshot
from app.schemas.api import (
    AnomalyResponse,
    AnomalyStatusPoint,
    AnomalyStatusResponse,
    DashboardSummaryResponse,
    OptimizationExecutionResponse,
    OptimizationRequest,
    RecommendationResponse,
    SyncResponse,
)
from app.services.anomaly_detection import AnomalyDetectionService
from app.services.ingestion import IngestionService
from app.services.optimization import OptimizationService
from app.services.recommendations import RecommendationService


class CostIntelligenceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def sync(self) -> SyncResponse:
        ingested_cost_records, ingested_resource_snapshots = IngestionService(self.db).ingest()
        anomalies_detected = AnomalyDetectionService(self.db).run()
        recommendations_generated = RecommendationService(self.db).generate()
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
                total_cost=float(row[2]),
            )
            for row in rows
        ]
        observed_days = len(points)
        min_days_required = 7
        latest_detection_run_at = self.db.execute(select(func.max(Anomaly.detected_at))).scalar_one()

        if observed_days == 0:
            readiness = "waiting_for_billing_history"
            status_message = "AWS billing history is not available yet, so the ML detector has nothing real to analyze."
        elif observed_days < min_days_required:
            readiness = "warming_up"
            status_message = (
                f"ML anomaly detection is warming up with {observed_days} of {min_days_required} required billing days."
            )
        else:
            readiness = "ready"
            status_message = (
                f"ML anomaly detection is ready with {observed_days} billing days available for baseline analysis."
            )

        return AnomalyStatusResponse(
            readiness=readiness,
            status_message=status_message,
            min_days_required=min_days_required,
            observed_days=observed_days,
            latest_detection_run_at=latest_detection_run_at,
            points=points,
        )

    def get_dashboard_summary(self) -> DashboardSummaryResponse:
        total_cost = self.db.execute(select(func.coalesce(func.sum(CostRecord.cost_amount), 0.0))).scalar_one()
        estimated_total = self.db.execute(
            select(func.coalesce(func.sum(ResourceSnapshot.monthly_cost_estimate), 0.0))
        ).scalar_one()
        anomaly_count = self.db.execute(select(func.count(Anomaly.id))).scalar_one()
        recommendation_count = self.db.execute(select(func.count(Recommendation.id))).scalar_one()
        estimated_monthly_savings = self.db.execute(
            select(func.coalesce(func.sum(Recommendation.estimated_monthly_savings), 0.0))
        ).scalar_one()
        last_cost_sync = self.db.execute(select(func.max(CostRecord.created_at))).scalar_one()
        last_snapshot_sync = self.db.execute(select(func.max(ResourceSnapshot.captured_at))).scalar_one()
        last_sync_at = max([value for value in [last_cost_sync, last_snapshot_sync] if value is not None], default=None)
        has_actual_cost = float(total_cost) > 0
        return DashboardSummaryResponse(
            total_cost=float(total_cost) if has_actual_cost else float(estimated_total),
            cost_source="actual_billing" if has_actual_cost else "estimated_pricing",
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
