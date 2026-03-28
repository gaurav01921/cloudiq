from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.aws.client import AwsConnector
from app.connectors.gcp.client import GcpConnector
from app.core.config import get_settings
from app.models import Recommendation
from app.schemas.api import OptimizationExecutionResponse, OptimizationRequest


class OptimizationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def execute(self, request: OptimizationRequest) -> list[OptimizationExecutionResponse]:
        query = select(Recommendation)
        if request.recommendation_ids:
            query = query.where(Recommendation.id.in_(request.recommendation_ids))
        recommendations = self.db.execute(query).scalars().all()
        if len(recommendations) > self.settings.optimization_max_actions_per_run and not request.bypass_safety_checks:
            return [
                OptimizationExecutionResponse(
                    recommendation_id=rec.id,
                    executed=False,
                    result={
                        "skipped": True,
                        "reason": (
                            f"Safety limit exceeded. Requested {len(recommendations)} actions, "
                            f"max allowed is {self.settings.optimization_max_actions_per_run} per run."
                        ),
                    },
                )
                for rec in recommendations
            ]

        aws_connector = AwsConnector() if self.settings.aws_enabled else None
        gcp_connector = (
            GcpConnector()
            if self.settings.gcp_enabled and self.settings.gcp_project_id and self.settings.gcp_billing_export_table
            else None
        )
        aws_identity = aws_connector.get_caller_identity() if aws_connector else None
        responses: list[OptimizationExecutionResponse] = []

        for recommendation in recommendations:
            recommendation.approved = recommendation.approved or request.auto_approve
            if not recommendation.approved and not request.force_execute:
                result = {"skipped": True, "reason": "Recommendation not approved."}
                recommendation.execution_result = result
                responses.append(
                    OptimizationExecutionResponse(
                        recommendation_id=recommendation.id,
                        executed=False,
                        result=result,
                    )
                )
                continue

            payload = recommendation.action_payload
            safety_result = self._evaluate_safety(
                recommendation=recommendation,
                payload=payload,
                request=request,
                aws_identity=aws_identity,
            )
            if safety_result is not None:
                recommendation.execution_result = safety_result
                responses.append(
                    OptimizationExecutionResponse(
                        recommendation_id=recommendation.id,
                        executed=False,
                        result=safety_result,
                    )
                )
                continue

            result: dict
            executed = False
            is_real_execution = bool(request.force_execute)

            if recommendation.provider == "aws" and aws_connector:
                try:
                    if payload["action"] == "stop_instance":
                        result = aws_connector.stop_instance(
                            instance_id=payload["resource_id"],
                            dry_run=not is_real_execution,
                        )
                        executed = is_real_execution
                    elif payload["action"] == "delete_volume":
                        result = aws_connector.delete_volume(
                            volume_id=payload["resource_id"],
                            dry_run=not is_real_execution,
                        )
                        executed = is_real_execution
                    elif payload["action"] == "release_address":
                        result = aws_connector.release_address(
                            allocation_id=payload["resource_id"],
                            dry_run=not is_real_execution,
                        )
                        executed = is_real_execution
                    elif payload["action"] in {
                        "review_rightsize",
                        "review_native_recommendation",
                        "review_stopped_instance",
                        "review_snapshot_cleanup",
                        "review_load_balancer",
                        "review_nat_gateway",
                        "review_rds_instance",
                    }:
                        result = {
                            "skipped": True,
                            "reason": "This recommendation is advisory and requires operator review before infrastructure changes.",
                            "action": payload["action"],
                            "instance_type": payload.get("safety_context", {}).get("instance_type"),
                            "cpu_utilization_avg": payload.get("safety_context", {}).get("cpu_utilization_avg"),
                            "recommendation_options": payload.get("recommendation_options"),
                            "stopped_age_days": payload.get("stopped_age_days"),
                            "snapshot_age_days": payload.get("snapshot_age_days"),
                            "recent_request_count": payload.get("recent_request_count"),
                            "recent_bytes_out": payload.get("recent_bytes_out"),
                            "database_connections_avg": payload.get("database_connections_avg"),
                        }
                    elif payload["action"] in {"investigate_anomaly", "review_compute_anomaly", "review_storage_anomaly"}:
                        result = {
                            "skipped": True,
                            "reason": "Anomaly-guided optimization is advisory and requires operator review.",
                            "anomaly_scope_key": payload.get("anomaly_scope_key"),
                            "suspected_overage": payload.get("suspected_overage"),
                            "anomaly_score": payload.get("anomaly_score"),
                        }
                    else:
                        result = {"skipped": True, "reason": f"Unsupported AWS action {payload['action']}"}
                except ClientError as exc:
                    result = {
                        "skipped": True,
                        "reason": exc.response.get("Error", {}).get("Message", "AWS API call failed."),
                        "error_code": exc.response.get("Error", {}).get("Code"),
                    }
            elif recommendation.provider == "demo":
                if payload["action"] in {
                    "investigate_anomaly",
                    "review_compute_anomaly",
                    "review_storage_anomaly",
                    "review_rightsize",
                    "review_native_recommendation",
                    "review_stopped_instance",
                    "review_snapshot_cleanup",
                    "review_load_balancer",
                    "review_nat_gateway",
                    "review_rds_instance",
                }:
                    if is_real_execution:
                        result = {
                            "simulated": True,
                            "action": payload["action"],
                            "resource_id": payload["resource_id"],
                            "message": "Demo mode simulated an anomaly-driven optimization review.",
                            "suspected_overage": payload.get("suspected_overage"),
                        }
                    else:
                        result = {
                            "simulated": True,
                            "dry_run": True,
                            "authorized": True,
                            "action": payload["action"],
                            "resource_id": payload["resource_id"],
                            "message": "Demo mode validated the anomaly-driven optimization review.",
                            "suspected_overage": payload.get("suspected_overage"),
                        }
                else:
                    if is_real_execution:
                        result = {
                            "simulated": True,
                            "action": payload["action"],
                            "resource_id": payload["resource_id"],
                            "message": "Demo mode simulated this optimization successfully.",
                        }
                    else:
                        result = {
                            "simulated": True,
                            "dry_run": True,
                            "authorized": True,
                            "action": payload["action"],
                            "resource_id": payload["resource_id"],
                            "message": "Demo mode validated this optimization successfully.",
                        }
                executed = is_real_execution
            elif recommendation.provider == "gcp" and gcp_connector:
                if payload["action"] == "stop_instance" and payload.get("instance_name") and payload.get("zone"):
                    result = gcp_connector.stop_instance(
                        instance_name=payload["instance_name"],
                        zone=payload["zone"],
                        dry_run=not is_real_execution,
                    )
                    executed = is_real_execution
                else:
                    result = {"skipped": True, "reason": "GCP instance name/zone missing for stop action."}
            else:
                result = {"skipped": True, "reason": "Provider connector unavailable."}

            recommendation.executed = recommendation.executed or executed
            recommendation.execution_result = result
            responses.append(
                OptimizationExecutionResponse(
                    recommendation_id=recommendation.id,
                    executed=executed,
                    result=result,
                )
            )

        self.db.commit()
        return responses

    def _evaluate_safety(
        self,
        recommendation: Recommendation,
        payload: dict,
        request: OptimizationRequest,
        aws_identity: dict | None,
    ) -> dict | None:
        if recommendation.provider == "demo":
            return None

        if request.bypass_safety_checks:
            return None

        if request.force_execute and self.settings.optimization_require_explicit_approval:
            if not recommendation.approved:
                return {
                    "skipped": True,
                    "reason": "Real execution requires explicit approval before force execution.",
                }
            if not self._has_successful_dry_run(recommendation):
                return {
                    "skipped": True,
                    "reason": "Real execution requires a successful prior dry run.",
                }

        if (
            request.force_execute
            and self.settings.optimization_block_root_credentials
            and aws_identity
            and str(aws_identity.get("Arn", "")).endswith(":root")
        ):
            return {
                "skipped": True,
                "reason": "Real execution is blocked when using AWS root credentials.",
            }

        safety_context = payload.get("safety_context", {})
        protected_tag_hit = self._matches_protected_tag(safety_context.get("tags", []))
        if protected_tag_hit:
            return {
                "skipped": True,
                "reason": (
                    f"Resource is protected by tag {protected_tag_hit['Key']}={protected_tag_hit.get('Value', '')}."
                ),
            }

        if payload.get("action") == "stop_instance" and safety_context.get("state") not in {None, "running"}:
            return {
                "skipped": True,
                "reason": f"Instance is not running. Current state: {safety_context.get('state')}.",
            }

        if payload.get("action") == "delete_volume" and safety_context.get("attachments"):
            return {
                "skipped": True,
                "reason": "Volume still has attachments and will not be deleted.",
            }

        if payload.get("action") == "release_address" and safety_context.get("association_id"):
            return {
                "skipped": True,
                "reason": "Elastic IP is still associated and will not be released.",
            }

        return None

    def _matches_protected_tag(self, tags: list[dict]) -> dict | None:
        protected_keys = {item.strip().lower() for item in self.settings.optimization_protected_tag_keys.split(",")}
        protected_values = {item.strip().lower() for item in self.settings.optimization_protected_tag_values.split(",")}
        for tag in tags:
            key = str(tag.get("Key", "")).strip()
            value = str(tag.get("Value", "")).strip()
            if key.lower() in protected_keys or value.lower() in protected_values:
                return {"Key": key, "Value": value}
        return None

    @staticmethod
    def _has_successful_dry_run(recommendation: Recommendation) -> bool:
        result = recommendation.execution_result or {}
        return bool(result.get("dry_run") and result.get("authorized"))
