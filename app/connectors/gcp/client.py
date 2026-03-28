from datetime import date, datetime, timedelta, timezone

from googleapiclient.discovery import build
from google.cloud import bigquery
from google.cloud import monitoring_v3

from app.core.config import get_settings


class GcpConnector:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.gcp_project_id:
            raise ValueError("GCP_PROJECT_ID is required for GCP ingestion.")
        if not settings.gcp_billing_export_table:
            raise ValueError("GCP_BILLING_EXPORT_TABLE is required for GCP billing ingestion.")
        self.project_id = settings.gcp_project_id
        self.billing_export_table = settings.gcp_billing_export_table
        self.bigquery = bigquery.Client(project=self.project_id)
        self.monitoring = monitoring_v3.MetricServiceClient()
        self.compute = build("compute", "v1", cache_discovery=False)

    def fetch_daily_costs(self, lookback_days: int) -> list[dict]:
        start = date.today() - timedelta(days=lookback_days)
        query = f"""
        SELECT
          DATE(usage_start_time) AS usage_date,
          service.description AS service,
          COALESCE(resource.global_name, 'aggregated') AS resource_id,
          SUM(cost) AS cost_amount,
          ANY_VALUE(currency) AS currency
        FROM `{self.billing_export_table}`
        WHERE DATE(usage_start_time) >= @start_date
        GROUP BY usage_date, service, resource_id
        ORDER BY usage_date ASC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start.isoformat()),
            ]
        )
        rows = self.bigquery.query(query, job_config=job_config).result()
        return [
            {
                "provider": "gcp",
                "account_id": None,
                "project_id": self.project_id,
                "service": row.service,
                "resource_id": row.resource_id,
                "usage_date": row.usage_date,
                "cost_amount": float(row.cost_amount),
                "currency": row.currency or "USD",
                "usage_quantity": None,
                "usage_unit": None,
                "metadata_json": {"source": "bigquery_billing_export"},
            }
            for row in rows
        ]

    def fetch_resource_snapshots(self) -> list[dict]:
        cpu_by_instance = self._cpu_by_instance()
        request = self.compute.instances().aggregatedList(project=self.project_id)
        snapshots: list[dict] = []
        while request is not None:
            response = request.execute()
            for zone_key, scoped in response.get("items", {}).items():
                for instance in scoped.get("instances", []):
                    instance_id = str(instance["id"])
                    zone = instance["zone"].split("/")[-1]
                    cpu_avg = cpu_by_instance.get(instance_id)
                    snapshots.append(
                        {
                            "provider": "gcp",
                            "account_id": None,
                            "project_id": self.project_id,
                            "resource_id": instance_id,
                            "resource_type": "gce_instance",
                            "region": zone,
                            "state": instance.get("status"),
                            "cpu_utilization_avg": cpu_avg,
                            "network_utilization_avg": None,
                            "monthly_cost_estimate": None,
                            "is_idle": bool(
                                instance.get("status") == "RUNNING" and cpu_avg is not None and cpu_avg < 5
                            ),
                            "metadata_json": {
                                "zone": zone,
                                "name": instance.get("name"),
                                "machine_type": instance.get("machineType", "").split("/")[-1],
                                "aggregated_key": zone_key,
                            },
                        }
                    )
            request = self.compute.instances().aggregatedList_next(previous_request=request, previous_response=response)
        return snapshots

    def stop_instance(self, instance_name: str, zone: str, dry_run: bool) -> dict:
        if dry_run:
            return {
                "action": "stop_instance",
                "instance_name": instance_name,
                "zone": zone,
                "dry_run": True,
            }
        operation = self.compute.instances().stop(
            project=self.project_id,
            zone=zone,
            instance=instance_name,
        ).execute()
        return {"action": "stop_instance", "instance_name": instance_name, "zone": zone, "response": operation}

    def _cpu_by_instance(self) -> dict[str, float]:
        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(datetime.now(tz=timezone.utc).timestamp())},
                "start_time": {"seconds": int((datetime.now(tz=timezone.utc) - timedelta(days=7)).timestamp())},
            }
        )
        request = monitoring_v3.ListTimeSeriesRequest(
            name=f"projects/{self.project_id}",
            filter='metric.type = "compute.googleapis.com/instance/cpu/utilization"',
            interval=interval,
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        )
        cpu_by_instance: dict[str, float] = {}
        for series in self.monitoring.list_time_series(request=request):
            instance_id = series.resource.labels.get("instance_id")
            if not instance_id:
                continue
            values = [point.value.double_value for point in series.points]
            if values:
                cpu_by_instance[instance_id] = round(sum(values) / len(values), 4) * 100
        return cpu_by_instance
