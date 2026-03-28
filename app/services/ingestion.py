from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.aws.client import AwsConnector
from app.connectors.gcp.client import GcpConnector
from app.core.config import get_settings
from app.core.retry import retry_call
from app.models import CostRecord, ResourceSnapshot
from app.services.demo_data import DemoDataService
from app.services.runtime_settings import RuntimeSettingsService


class IngestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def ingest(self) -> tuple[int, int]:
        ingested_cost_records = 0
        ingested_resource_snapshots = 0
        mode = RuntimeSettingsService(self.db).get_data_mode()

        if mode in {"demo", "hybrid"}:
            demo = DemoDataService(self.settings.ingestion_lookback_days)
            ingested_cost_records += self._upsert_cost_records(demo.generate_cost_records())
            ingested_resource_snapshots += self._replace_resource_snapshots("demo", demo.generate_resource_snapshots())

        if mode in {"live", "hybrid"} and self.settings.aws_enabled:
            aws = AwsConnector()
            try:
                ingested_cost_records += self._upsert_cost_records(
                    retry_call(
                        lambda: aws.fetch_daily_costs(self.settings.ingestion_lookback_days),
                        attempts=self.settings.retry_attempts,
                        base_delay_seconds=self.settings.retry_base_delay_seconds,
                        retryable_exceptions=(ClientError,),
                    )
                )
            except ClientError:
                pass
            ingested_resource_snapshots += self._replace_resource_snapshots(
                "aws",
                retry_call(
                    aws.fetch_resource_snapshots,
                    attempts=self.settings.retry_attempts,
                    base_delay_seconds=self.settings.retry_base_delay_seconds,
                    retryable_exceptions=(ClientError,),
                ),
            )

        if (
            mode in {"live", "hybrid"}
            and self.settings.gcp_enabled
            and self.settings.gcp_project_id
            and self.settings.gcp_billing_export_table
        ):
            gcp = GcpConnector()
            ingested_cost_records += self._upsert_cost_records(
                retry_call(
                    lambda: gcp.fetch_daily_costs(self.settings.ingestion_lookback_days),
                    attempts=self.settings.retry_attempts,
                    base_delay_seconds=self.settings.retry_base_delay_seconds,
                    retryable_exceptions=(Exception,),
                )
            )
            ingested_resource_snapshots += self._replace_resource_snapshots(
                "gcp",
                retry_call(
                    gcp.fetch_resource_snapshots,
                    attempts=self.settings.retry_attempts,
                    base_delay_seconds=self.settings.retry_base_delay_seconds,
                    retryable_exceptions=(Exception,),
                ),
            )

        self.db.commit()
        return ingested_cost_records, ingested_resource_snapshots

    def _upsert_cost_records(self, records: list[dict]) -> int:
        count = 0
        for record in records:
            existing = self.db.execute(
                select(CostRecord).where(
                    CostRecord.provider == record["provider"],
                    CostRecord.service == record["service"],
                    CostRecord.usage_date == record["usage_date"],
                    CostRecord.resource_id == record["resource_id"],
                )
            ).scalar_one_or_none()
            if existing:
                existing.cost_amount = record["cost_amount"]
                existing.currency = record["currency"]
                existing.usage_quantity = record["usage_quantity"]
                existing.usage_unit = record["usage_unit"]
                existing.metadata_json = record["metadata_json"]
            else:
                self.db.add(CostRecord(**record))
            count += 1
        return count

    def _replace_resource_snapshots(self, provider: str, snapshots: list[dict]) -> int:
        self.db.query(ResourceSnapshot).filter(ResourceSnapshot.provider == provider).delete()
        for snapshot in snapshots:
            self.db.add(ResourceSnapshot(**snapshot))
        return len(snapshots)
