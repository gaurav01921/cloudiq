from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.aws.client import AwsConnector
from app.connectors.gcp.client import GcpConnector
from app.core.config import get_settings
from app.models import CostRecord, ResourceSnapshot


class IngestionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def ingest(self) -> tuple[int, int]:
        ingested_cost_records = 0
        ingested_resource_snapshots = 0

        if self.settings.aws_enabled:
            aws = AwsConnector()
            try:
                ingested_cost_records += self._upsert_cost_records(
                    aws.fetch_daily_costs(self.settings.ingestion_lookback_days)
                )
            except ClientError:
                pass
            ingested_resource_snapshots += self._replace_resource_snapshots("aws", aws.fetch_resource_snapshots())

        if self.settings.gcp_enabled and self.settings.gcp_project_id and self.settings.gcp_billing_export_table:
            gcp = GcpConnector()
            ingested_cost_records += self._upsert_cost_records(
                gcp.fetch_daily_costs(self.settings.ingestion_lookback_days)
            )
            ingested_resource_snapshots += self._replace_resource_snapshots("gcp", gcp.fetch_resource_snapshots())

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
