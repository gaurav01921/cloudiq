from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Recommendation, ResourceSnapshot


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
            if snapshot.provider == "aws" and snapshot.resource_type == "ec2_instance" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 10.0
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider="aws",
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
                snapshot.provider == "aws"
                and snapshot.resource_type == "ec2_instance"
                and snapshot.state == "running"
                and snapshot.cpu_utilization_avg is not None
                and 5 <= snapshot.cpu_utilization_avg < 20
            ):
                savings = round((snapshot.monthly_cost_estimate or 0.0) * 0.3, 2)
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider="aws",
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
            if snapshot.provider == "aws" and snapshot.resource_type == "ebs_volume" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 5.0
                if savings >= self.settings.optimization_min_monthly_savings:
                    self.db.add(
                        Recommendation(
                            provider="aws",
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
            if snapshot.provider == "aws" and snapshot.resource_type == "elastic_ip" and snapshot.is_idle:
                savings = snapshot.monthly_cost_estimate or 3.6
                if savings > 0:
                    self.db.add(
                        Recommendation(
                            provider="aws",
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
        self.db.commit()
        return created
