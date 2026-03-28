from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.aws.client import AwsConnector
from app.core.config import get_settings
from app.models import Anomaly, Recommendation, ResourceSnapshot


class RecommendationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def generate(self) -> int:
        self.db.execute(delete(Recommendation))
        snapshots = self.db.execute(select(ResourceSnapshot)).scalars().all()
        created = 0
        for snapshot in snapshots:
            metadata = snapshot.metadata_json or {}
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "ec2_instance" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 10.0
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="stop_idle_instance",
                            resource_id=snapshot.resource_id,
                            description=f"Stop idle EC2 instance {snapshot.resource_id}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "stop_instance",
                                "resource_id": snapshot.resource_id,
                                "region": snapshot.region,
                                "safety_context": {
                                    "state": snapshot.state,
                                    "tags": metadata.get("tags", []),
                                    "resource_type": snapshot.resource_type,
                                },
                            },
                        )
                    )
                    created += 1
            if (
                snapshot.provider in {"aws", "demo"}
                and snapshot.resource_type == "ec2_instance"
                and snapshot.state == "running"
                and snapshot.cpu_utilization_avg is not None
                and 5 <= snapshot.cpu_utilization_avg < 20
            ):
                savings = round((snapshot.monthly_cost_estimate or 0.0) * 0.3, 2)
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="rightsize_underutilized_instance",
                            resource_id=snapshot.resource_id,
                            description=f"Rightsize underutilized EC2 instance {snapshot.resource_id}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "review_rightsize",
                                "resource_id": snapshot.resource_id,
                                "region": snapshot.region,
                                "safety_context": {
                                    "state": snapshot.state,
                                    "tags": metadata.get("tags", []),
                                    "resource_type": snapshot.resource_type,
                                    "instance_type": metadata.get("instance_type"),
                                    "cpu_utilization_avg": snapshot.cpu_utilization_avg,
                                },
                            },
                        )
                    )
                    created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "ec2_instance" and snapshot.state == "stopped":
                stopped_since = metadata.get("stopped_since")
                stopped_age_days = self._age_days(stopped_since)
                savings = snapshot.monthly_cost_estimate or 0.0
                if stopped_age_days >= 14 and savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="review_long_stopped_instance",
                            resource_id=snapshot.resource_id,
                            description=f"Review long-stopped EC2 instance {snapshot.resource_id}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "review_stopped_instance",
                                "resource_id": snapshot.resource_id,
                                "region": snapshot.region,
                                "stopped_age_days": stopped_age_days,
                                "safety_context": {
                                    "state": snapshot.state,
                                    "tags": metadata.get("tags", []),
                                    "resource_type": snapshot.resource_type,
                                },
                            },
                        )
                    )
                    created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "ebs_volume" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 5.0
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="delete_unattached_volume",
                            resource_id=snapshot.resource_id,
                            description=f"Delete unattached EBS volume {snapshot.resource_id}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "delete_volume",
                                "resource_id": snapshot.resource_id,
                                "region": snapshot.region,
                                "safety_context": {
                                    "state": snapshot.state,
                                    "attachments": metadata.get("attachments", []),
                                    "resource_type": snapshot.resource_type,
                                    "tags": metadata.get("tags", []),
                                },
                            },
                        )
                    )
                    created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "ebs_snapshot":
                age_days = int(metadata.get("age_days") or 0)
                savings = snapshot.monthly_cost_estimate or 0.0
                if age_days >= 30 and savings >= 1:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="review_old_snapshot",
                            resource_id=snapshot.resource_id,
                            description=f"Review old EBS snapshot {snapshot.resource_id}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "review_snapshot_cleanup",
                                "resource_id": snapshot.resource_id,
                                "snapshot_age_days": age_days,
                                "region": snapshot.region,
                                "safety_context": {
                                    "state": snapshot.state,
                                    "tags": metadata.get("tags", []),
                                    "resource_type": snapshot.resource_type,
                                },
                            },
                        )
                    )
                    created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "elastic_ip" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 3.6
                if savings > 0:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="release_unattached_eip",
                            resource_id=snapshot.resource_id,
                            description=f"Release unattached Elastic IP {metadata.get('public_ip', snapshot.resource_id)}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "release_address",
                                "resource_id": snapshot.resource_id,
                                "region": snapshot.region,
                                "safety_context": {
                                    "state": snapshot.state,
                                    "association_id": metadata.get("association_id"),
                                    "tags": metadata.get("tags", []),
                                    "resource_type": snapshot.resource_type,
                                    "public_ip": metadata.get("public_ip"),
                                },
                            },
                        )
                    )
                    created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "load_balancer" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 16.2
                self.db.add(
                    Recommendation(
                        provider=snapshot.provider,
                        recommendation_type="review_idle_load_balancer",
                        resource_id=snapshot.resource_id,
                        description=f"Review low-traffic load balancer {metadata.get('name', snapshot.resource_id)}",
                        estimated_monthly_savings=savings,
                        action_payload={
                            "action": "review_load_balancer",
                            "resource_id": snapshot.resource_id,
                            "recent_request_count": snapshot.network_utilization_avg,
                            "region": snapshot.region,
                        },
                    )
                )
                created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "nat_gateway" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 32.4
                self.db.add(
                    Recommendation(
                        provider=snapshot.provider,
                        recommendation_type="review_idle_nat_gateway",
                        resource_id=snapshot.resource_id,
                        description=f"Review low-traffic NAT gateway {snapshot.resource_id}",
                        estimated_monthly_savings=savings,
                        action_payload={
                            "action": "review_nat_gateway",
                            "resource_id": snapshot.resource_id,
                            "recent_bytes_out": snapshot.network_utilization_avg,
                            "region": snapshot.region,
                        },
                    )
                )
                created += 1
            if snapshot.provider in {"aws", "demo"} and snapshot.resource_type == "rds_instance" and snapshot.is_idle:
                savings = round((snapshot.monthly_cost_estimate or 0.0) * 0.35, 2)
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider=snapshot.provider,
                            recommendation_type="review_idle_rds_instance",
                            resource_id=snapshot.resource_id,
                            description=f"Review low-utilization RDS instance {snapshot.resource_id}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "review_rds_instance",
                                "resource_id": snapshot.resource_id,
                                "cpu_utilization_avg": snapshot.cpu_utilization_avg,
                                "database_connections_avg": snapshot.network_utilization_avg,
                                "region": snapshot.region,
                            },
                        )
                    )
                    created += 1
            if snapshot.provider == "gcp" and snapshot.resource_type == "gce_instance" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 10.0
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider="gcp",
                            recommendation_type="stop_idle_instance",
                            resource_id=snapshot.resource_id,
                            description=f"Stop idle GCE instance {metadata.get('name', snapshot.resource_id)}",
                            estimated_monthly_savings=savings,
                            action_payload={
                                "action": "stop_instance",
                                "resource_id": snapshot.resource_id,
                                "instance_name": metadata.get("name"),
                                "zone": metadata.get("zone"),
                            },
                        )
                    )
                    created += 1
        created += self._generate_native_provider_recommendations()
        created += self._generate_anomaly_recommendations()
        self.db.commit()
        return created

    def _generate_native_provider_recommendations(self) -> int:
        if not self.settings.aws_enabled:
            return 0
        try:
            native_items = AwsConnector().fetch_native_recommendations()
        except Exception:
            return 0
        for item in native_items:
            self.db.add(Recommendation(**item))
        return len(native_items)

    def _generate_anomaly_recommendations(self) -> int:
        anomalies = self.db.execute(select(Anomaly).order_by(Anomaly.detected_at.desc())).scalars().all()
        created = 0
        for anomaly in anomalies:
            delta = max(float(anomaly.observed_cost - anomaly.expected_cost), 0.0)
            if delta <= 0:
                continue

            recommendation_type = "investigate_cost_anomaly"
            description = f"Investigate spend anomaly for {anomaly.scope_key}"
            action = "investigate_anomaly"

            if anomaly.provider in {"aws", "demo"} and "Compute" in anomaly.scope_key:
                description = f"Review EC2 spend anomaly for {anomaly.scope_key} and reduce idle compute"
                action = "review_compute_anomaly"
                recommendation_type = "review_compute_cost_anomaly"
            elif anomaly.provider in {"aws", "demo"} and "Block Store" in anomaly.scope_key:
                description = f"Review EBS spend anomaly for {anomaly.scope_key} and clean up unattached storage"
                action = "review_storage_anomaly"
                recommendation_type = "review_storage_cost_anomaly"

            self.db.add(
                Recommendation(
                    provider=anomaly.provider,
                    recommendation_type=recommendation_type,
                    resource_id=anomaly.scope_key,
                    description=description,
                    estimated_monthly_savings=round(delta, 2),
                    action_payload={
                        "action": action,
                        "resource_id": anomaly.scope_key,
                        "anomaly_scope": anomaly.scope,
                        "anomaly_scope_key": anomaly.scope_key,
                        "anomaly_usage_date": anomaly.usage_date,
                        "anomaly_score": anomaly.anomaly_score,
                        "observed_cost": anomaly.observed_cost,
                        "expected_cost": anomaly.expected_cost,
                        "suspected_overage": round(delta, 2),
                    },
                )
            )
            created += 1
        return created

    @staticmethod
    def _age_days(value: str | None) -> int:
        if not value:
            return 0
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - parsed).days, 0)
