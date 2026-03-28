from app.core.config import get_settings


class TopologyService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def describe(self) -> dict:
        return {
            "architecture_style": "centralized_ccm_control_plane",
            "deployment_shape": {
                "web_service": {
                    "role": "ui_and_api_gateway",
                    "entrypoint": "python -m app.cli runserver --host 0.0.0.0 --port 8000",
                    "modules": [
                        "app.main",
                        "app.api.routes",
                        "app.api.auth_routes",
                        "app.static",
                    ],
                },
                "batch_worker": {
                    "role": "ccm_batch_service",
                    "entrypoint": "python -m app.cli worker --interval 300",
                    "modules": [
                        "app.services.batch_service",
                        "app.services.ingestion",
                        "app.services.anomaly_detection",
                        "app.services.recommendations",
                        "app.services.optimization",
                    ],
                },
                "scheduler_service": {
                    "role": "ccm_scheduler",
                    "entrypoint": "python -m app.cli scheduler",
                    "modules": [
                        "app.tasks.scheduler",
                        "app.services.job_monitor",
                        "app.services.alerts",
                    ],
                },
            },
            "cloud_sources": {
                "aws_customer_infra": {
                    "enabled": self.settings.aws_enabled,
                    "services": [
                        "Cost Explorer",
                        "EC2",
                        "EBS",
                        "Elastic IP",
                        "Load Balancer",
                        "NAT Gateway",
                        "Snapshots",
                        "RDS",
                        "CloudWatch",
                        "Compute Optimizer",
                    ],
                },
                "gcp_customer_infra": {
                    "enabled": self.settings.gcp_enabled,
                    "services": [
                        "BigQuery billing export",
                        "Compute Engine",
                        "Cloud Monitoring",
                    ],
                },
            },
            "logical_modules": [
                {
                    "name": "CCM Manager",
                    "responsibilities": [
                        "orchestrate syncs",
                        "coordinate anomaly detection",
                        "generate recommendations",
                        "route optimization actions",
                    ],
                    "current_mapping": [
                        "app.services.cost_intelligence",
                        "app.services.batch_service",
                    ],
                },
                {
                    "name": "Batch Service",
                    "responsibilities": [
                        "run scheduled sync cycles",
                        "pull cloud inventory and billing data",
                    ],
                    "current_mapping": [
                        "app.services.ingestion",
                        "app.services.batch_service",
                    ],
                },
                {
                    "name": "Event Service",
                    "responsibilities": [
                        "record audit events",
                        "store job runs",
                        "surface alerts and sync markers",
                    ],
                    "current_mapping": [
                        "app.services.audit",
                        "app.services.job_monitor",
                        "app.services.alerts",
                    ],
                },
                {
                    "name": "Dashboard Services",
                    "responsibilities": [
                        "serve UI",
                        "show timelines",
                        "manage auth and RBAC",
                    ],
                    "current_mapping": [
                        "app.api.routes",
                        "app.api.auth_routes",
                        "app.static",
                    ],
                },
            ],
            "managed_services_mapping": [
                {
                    "target_service": "Cloud SQL / Timeseries store",
                    "current_component": "SQLAlchemy database",
                    "current_state": self.settings.database_url,
                },
                {
                    "target_service": "Cloud Scheduler",
                    "current_component": "APScheduler",
                    "current_state": "enabled" if self.settings.scheduler_enabled else "disabled",
                },
                {
                    "target_service": "Pub/Sub or event bus",
                    "current_component": "job runs + audit history + API-triggered workflows",
                    "current_state": "logical event flow implemented in-process",
                },
                {
                    "target_service": "Memorystore / Redis",
                    "current_component": "session middleware + in-process state",
                    "current_state": "not externalized yet",
                },
                {
                    "target_service": "Cloud Storage",
                    "current_component": "provider billing exports and local static assets",
                    "current_state": "source-integrated",
                },
            ],
        }
