from datetime import date, datetime, timedelta
import json

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings


class AwsConnector:
    def __init__(self) -> None:
        settings = get_settings()
        self.region = settings.aws_region
        self.account_id = settings.aws_account_id
        client_kwargs = self._client_kwargs(settings)
        self.sts = boto3.client("sts", region_name=self.region, **client_kwargs)
        self.ce = boto3.client("ce", region_name="us-east-1", **client_kwargs)
        self.ec2 = boto3.client("ec2", region_name=self.region, **client_kwargs)
        self.cw = boto3.client("cloudwatch", region_name=self.region, **client_kwargs)
        self.pricing = boto3.client("pricing", region_name="us-east-1", **client_kwargs)

    @staticmethod
    def _client_kwargs(settings) -> dict:
        kwargs: dict[str, str] = {}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
        return kwargs

    def get_caller_identity(self) -> dict:
        return self.sts.get_caller_identity()

    def cost_explorer_is_ready(self) -> bool:
        try:
            self.ce.get_cost_and_usage(
                TimePeriod={"Start": (date.today() - timedelta(days=1)).isoformat(), "End": date.today().isoformat()},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
            )
            return True
        except ClientError:
            return False

    def fetch_daily_costs(self, lookback_days: int) -> list[dict]:
        end = date.today()
        start = end - timedelta(days=lookback_days)
        response = self.ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY",
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        records: list[dict] = []
        for bucket in response.get("ResultsByTime", []):
            bucket_date = date.fromisoformat(bucket["TimePeriod"]["Start"])
            for group in bucket.get("Groups", []):
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                usage = float(group["Metrics"]["UsageQuantity"]["Amount"])
                records.append(
                    {
                        "provider": "aws",
                        "account_id": self.account_id,
                        "project_id": None,
                        "service": group["Keys"][0],
                        "resource_id": "aggregated",
                        "usage_date": bucket_date,
                        "cost_amount": amount,
                        "currency": group["Metrics"]["UnblendedCost"]["Unit"],
                        "usage_quantity": usage,
                        "usage_unit": group["Metrics"]["UsageQuantity"]["Unit"],
                        "metadata_json": {"granularity": "DAILY"},
                    }
                )
        return records

    def fetch_resource_snapshots(self) -> list[dict]:
        snapshots: list[dict] = []
        reservations = self.ec2.describe_instances().get("Reservations", [])
        for reservation in reservations:
            for instance in reservation.get("Instances", []):
                instance_id = instance["InstanceId"]
                state = instance.get("State", {}).get("Name")
                instance_type = instance.get("InstanceType")
                platform_details = instance.get("PlatformDetails") or "Linux/UNIX"
                cpu_avg = self._metric_average(
                    namespace="AWS/EC2",
                    metric_name="CPUUtilization",
                    dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    statistic="Average",
                )
                network_avg = self._metric_average(
                    namespace="AWS/EC2",
                    metric_name="NetworkOut",
                    dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    statistic="Average",
                )
                monthly_cost_estimate = self.estimate_instance_monthly_cost(
                    instance_type=instance_type,
                    platform_details=platform_details,
                    state=state,
                )
                snapshots.append(
                    {
                        "provider": "aws",
                        "account_id": self.account_id,
                        "project_id": None,
                        "resource_id": instance_id,
                        "resource_type": "ec2_instance",
                        "region": instance.get("Placement", {}).get("AvailabilityZone", "")[:-1] or self.region,
                        "state": state,
                        "cpu_utilization_avg": cpu_avg,
                        "network_utilization_avg": network_avg,
                        "monthly_cost_estimate": monthly_cost_estimate,
                        "is_idle": bool(
                            state == "running" and cpu_avg is not None and cpu_avg < 5 and (network_avg or 0) < 10000
                        ),
                        "metadata_json": {
                            "instance_type": instance_type,
                            "platform_details": platform_details,
                            "launch_time": instance.get("LaunchTime").isoformat() if instance.get("LaunchTime") else None,
                            "vpc_id": instance.get("VpcId"),
                            "tags": instance.get("Tags", []),
                            "cost_source": "pricing_api",
                        },
                    }
                )

        volumes = self.ec2.describe_volumes(
            Filters=[{"Name": "status", "Values": ["available"]}]
        ).get("Volumes", [])
        for volume in volumes:
            size_gb = volume.get("Size", 0)
            volume_type = volume.get("VolumeType", "gp3")
            snapshots.append(
                {
                    "provider": "aws",
                    "account_id": self.account_id,
                    "project_id": None,
                    "resource_id": volume["VolumeId"],
                    "resource_type": "ebs_volume",
                    "region": volume.get("AvailabilityZone", "")[:-1] or self.region,
                    "state": volume.get("State"),
                    "cpu_utilization_avg": None,
                    "network_utilization_avg": None,
                    "monthly_cost_estimate": self.estimate_ebs_monthly_cost(volume_type=volume_type, size_gb=size_gb),
                    "is_idle": True,
                    "metadata_json": {
                        "size_gb": size_gb,
                        "volume_type": volume_type,
                        "attachments": volume.get("Attachments", []),
                        "cost_source": "pricing_api",
                    },
                }
            )

        addresses = self.ec2.describe_addresses().get("Addresses", [])
        for address in addresses:
            allocation_id = address.get("AllocationId") or address.get("PublicIp")
            is_attached = bool(address.get("AssociationId") or address.get("InstanceId") or address.get("NetworkInterfaceId"))
            snapshots.append(
                {
                    "provider": "aws",
                    "account_id": self.account_id,
                    "project_id": None,
                    "resource_id": allocation_id,
                    "resource_type": "elastic_ip",
                    "region": self.region,
                    "state": "attached" if is_attached else "unattached",
                    "cpu_utilization_avg": None,
                    "network_utilization_avg": None,
                    "monthly_cost_estimate": 0.0 if is_attached else round(0.005 * 24 * 30, 2),
                    "is_idle": not is_attached,
                    "metadata_json": {
                        "public_ip": address.get("PublicIp"),
                        "allocation_id": address.get("AllocationId"),
                        "association_id": address.get("AssociationId"),
                        "instance_id": address.get("InstanceId"),
                        "network_interface_id": address.get("NetworkInterfaceId"),
                        "tags": address.get("Tags", []),
                        "cost_source": "pricing_api",
                    },
                }
            )
        return snapshots

    def stop_instance(self, instance_id: str, dry_run: bool) -> dict:
        try:
            response = self.ec2.stop_instances(InstanceIds=[instance_id], DryRun=dry_run)
            return {"action": "stop_instance", "instance_id": instance_id, "response": response}
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if dry_run and error_code == "DryRunOperation":
                return {
                    "action": "stop_instance",
                    "instance_id": instance_id,
                    "dry_run": True,
                    "authorized": True,
                    "message": "Dry run succeeded. AWS confirmed the stop action is permitted.",
                }
            raise

    def delete_volume(self, volume_id: str, dry_run: bool) -> dict:
        if dry_run:
            return {"action": "delete_volume", "volume_id": volume_id, "dry_run": True}
        self.ec2.delete_volume(VolumeId=volume_id)
        return {"action": "delete_volume", "volume_id": volume_id, "deleted": True}

    def release_address(self, allocation_id: str, dry_run: bool) -> dict:
        if dry_run:
            return {
                "action": "release_address",
                "allocation_id": allocation_id,
                "dry_run": True,
                "authorized": True,
            }
        self.ec2.release_address(AllocationId=allocation_id)
        return {"action": "release_address", "allocation_id": allocation_id, "released": True}

    def _metric_average(
        self,
        namespace: str,
        metric_name: str,
        dimensions: list[dict],
        statistic: str,
    ) -> float | None:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=7)
        datapoints = self.cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=3600,
            Statistics=[statistic],
        ).get("Datapoints", [])
        if not datapoints:
            return None
        values = [point[statistic] for point in datapoints if statistic in point]
        return round(sum(values) / len(values), 2) if values else None

    def estimate_instance_monthly_cost(self, instance_type: str | None, platform_details: str, state: str | None) -> float:
        if not instance_type or state in {"terminated", "stopped", "shutting-down"}:
            return 0.0
        operating_system = "Windows" if "windows" in platform_details.lower() else "Linux"
        filters = [
            {"Type": "TERM_MATCH", "Field": "location", "Value": self._pricing_location()},
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        ]
        if operating_system == "Linux":
            filters.append({"Type": "TERM_MATCH", "Field": "licenseModel", "Value": "No License required"})
        hourly_price = self._price_from_pricing_api(service_code="AmazonEC2", filters=filters, unit="Hrs")
        return round(hourly_price * 24 * 30, 2) if hourly_price is not None else 0.0

    def estimate_ebs_monthly_cost(self, volume_type: str, size_gb: int) -> float:
        volume_api_name = {
            "gp2": "General Purpose",
            "gp3": "General Purpose",
            "io1": "Provisioned IOPS",
            "io2": "Provisioned IOPS",
            "st1": "Throughput Optimized HDD",
            "sc1": "Cold HDD",
            "standard": "Magnetic",
        }.get(volume_type, "General Purpose")
        filters = [
            {"Type": "TERM_MATCH", "Field": "location", "Value": self._pricing_location()},
            {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
            {"Type": "TERM_MATCH", "Field": "volumeApiName", "Value": volume_api_name},
        ]
        monthly_per_gb = self._price_from_pricing_api(service_code="AmazonEC2", filters=filters, unit="GB-Mo")
        if monthly_per_gb is None:
            fallback = 0.08 if volume_type in {"gp2", "gp3"} else 0.1
            return round(size_gb * fallback, 2)
        return round(monthly_per_gb * size_gb, 2)

    def _price_from_pricing_api(self, service_code: str, filters: list[dict], unit: str) -> float | None:
        try:
            response = self.pricing.get_products(ServiceCode=service_code, Filters=filters, MaxResults=5)
        except ClientError:
            return None
        for price_item in response.get("PriceList", []):
            parsed = json.loads(price_item)
            for term in parsed.get("terms", {}).get("OnDemand", {}).values():
                for dimension in term.get("priceDimensions", {}).values():
                    if dimension.get("unit") == unit:
                        return float(dimension["pricePerUnit"]["USD"])
        return None

    def _pricing_location(self) -> str:
        return {
            "eu-north-1": "EU (Stockholm)",
            "us-east-1": "US East (N. Virginia)",
            "us-east-2": "US East (Ohio)",
            "us-west-1": "US West (N. California)",
            "us-west-2": "US West (Oregon)",
        }.get(self.region, self.region)
