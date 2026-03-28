from datetime import date, datetime, timedelta


class DemoDataService:
    def __init__(self, lookback_days: int) -> None:
        self.lookback_days = lookback_days

    def generate_cost_records(self) -> list[dict]:
        end = date.today()
        records: list[dict] = []
        services = [
            ("Amazon Elastic Compute Cloud - Compute", 7.5),
            ("Amazon Elastic Block Store", 2.8),
            ("AWS Data Transfer", 1.4),
        ]
        for offset in range(self.lookback_days):
            usage_date = end - timedelta(days=self.lookback_days - offset)
            for idx, (service, base) in enumerate(services):
                multiplier = 1.0
                if offset == self.lookback_days - 3 and idx == 0:
                    multiplier = 2.4
                records.append(
                    {
                        "provider": "demo",
                        "account_id": "demo-account",
                        "project_id": None,
                        "service": service,
                        "resource_id": "aggregated",
                        "usage_date": usage_date,
                        "cost_amount": round(base * multiplier, 2),
                        "currency": "USD",
                        "usage_quantity": round(24 * multiplier, 2),
                        "usage_unit": "Hrs",
                        "metadata_json": {"source": "demo_mode"},
                    }
                )
        return records

    def generate_resource_snapshots(self) -> list[dict]:
        captured = datetime.utcnow()
        return [
            {
                "provider": "demo",
                "account_id": "demo-account",
                "project_id": None,
                "resource_id": "demo-i-001",
                "resource_type": "ec2_instance",
                "region": "demo-region-1",
                "state": "running",
                "cpu_utilization_avg": 1.8,
                "network_utilization_avg": 600.0,
                "monthly_cost_estimate": 18.5,
                "is_idle": True,
                "metadata_json": {
                    "instance_type": "t3.small",
                    "tags": [{"Key": "Environment", "Value": "demo"}],
                    "cost_source": "demo_mode",
                },
                "captured_at": captured,
            },
            {
                "provider": "demo",
                "account_id": "demo-account",
                "project_id": None,
                "resource_id": "demo-eip-001",
                "resource_type": "elastic_ip",
                "region": "demo-region-1",
                "state": "unattached",
                "cpu_utilization_avg": None,
                "network_utilization_avg": None,
                "monthly_cost_estimate": 3.6,
                "is_idle": True,
                "metadata_json": {
                    "public_ip": "198.51.100.42",
                    "tags": [],
                    "cost_source": "demo_mode",
                },
                "captured_at": captured,
            },
        ]
