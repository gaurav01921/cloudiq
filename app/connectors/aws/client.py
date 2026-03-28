from datetime import date, datetime, timedelta, timezone
import json
import re

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
        self.budgets = boto3.client("budgets", region_name="us-east-1", **client_kwargs)
        self.ec2 = boto3.client("ec2", region_name=self.region, **client_kwargs)
        self.cw = boto3.client("cloudwatch", region_name=self.region, **client_kwargs)
        self.pricing = boto3.client("pricing", region_name="us-east-1", **client_kwargs)
        self.elbv2 = boto3.client("elbv2", region_name=self.region, **client_kwargs)
        self.rds = boto3.client("rds", region_name=self.region, **client_kwargs)
        self.compute_optimizer = boto3.client("compute-optimizer", region_name=self.region, **client_kwargs)

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
                            "state_transition_reason": instance.get("StateTransitionReason"),
                            "stopped_since": self._stopped_since(instance.get("StateTransitionReason")),
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
                        "start_time": volume.get("CreateTime").isoformat() if volume.get("CreateTime") else None,
                        "tags": volume.get("Tags", []),
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
        snapshots.extend(self._fetch_load_balancer_snapshots())
        snapshots.extend(self._fetch_nat_gateway_snapshots())
        snapshots.extend(self._fetch_snapshot_snapshots())
        snapshots.extend(self._fetch_rds_snapshots())
        return snapshots

    def fetch_native_recommendations(self) -> list[dict]:
        recommendations: list[dict] = []
        recommendations.extend(self.fetch_budget_recommendations())
        try:
            paginator = self.compute_optimizer.get_paginator("get_ec2_instance_recommendations")
            for page in paginator.paginate():
                for item in page.get("instanceRecommendations", []):
                    if item.get("finding") not in {"OVER_PROVISIONED", "OPTIMIZED"}:
                        continue
                    savings = float(
                        item.get("savingsOpportunity", {})
                        .get("estimatedMonthlySavings", {})
                        .get("value", 0.0)
                    )
                    if savings < self.settings.optimization_min_monthly_savings:
                        continue
                    instance_arn = item.get("instanceArn", "")
                    instance_id = instance_arn.rsplit("/", 1)[-1] if instance_arn else item.get("instanceName", "ec2")
                    recommendations.append(
                        {
                            "provider": "aws",
                            "recommendation_type": "native_rightsize_instance",
                            "resource_id": instance_id,
                            "description": f"AWS Compute Optimizer recommends rightsizing instance {instance_id}",
                            "estimated_monthly_savings": round(savings, 2),
                            "action_payload": {
                                "action": "review_native_recommendation",
                                "resource_id": instance_id,
                                "source": "aws_compute_optimizer",
                                "finding": item.get("finding"),
                                "recommendation_options": item.get("recommendationOptions", []),
                                "lookback_period_days": item.get("lookBackPeriodInDays"),
                            },
                        }
                    )
        except ClientError:
            pass
        return recommendations

    def fetch_native_anomalies(self, lookback_days: int) -> list[dict]:
        start = date.today() - timedelta(days=lookback_days)
        end = date.today()
        anomalies: list[dict] = []
        try:
            monitors = self.ce.get_anomaly_monitors(MaxResults=10).get("AnomalyMonitors", [])
        except ClientError:
            return anomalies

        for monitor in monitors:
            monitor_arn = monitor.get("MonitorArn")
            if not monitor_arn:
                continue
            next_token = None
            while True:
                kwargs = {
                    "MonitorArn": monitor_arn,
                    "DateInterval": {"StartDate": start.isoformat(), "EndDate": end.isoformat()},
                    "MaxResults": 100,
                }
                if next_token:
                    kwargs["NextPageToken"] = next_token
                try:
                    response = self.ce.get_anomalies(**kwargs)
                except ClientError:
                    break
                for item in response.get("Anomalies", []):
                    impact = item.get("Impact", {})
                    actual = float(impact.get("TotalActualSpend", 0.0) or 0.0)
                    expected = float(impact.get("TotalExpectedSpend", 0.0) or 0.0)
                    total_impact = float(impact.get("TotalImpact", max(actual - expected, 0.0)) or 0.0)
                    root_causes = item.get("RootCauses", [])
                    scope_key = (
                        item.get("DimensionValue")
                        or (root_causes[0].get("Service") if root_causes else None)
                        or monitor.get("MonitorName")
                        or "AWS Native Cost Anomaly"
                    )
                    raw_score = (
                        item.get("AnomalyScore", {}).get("CurrentScore")
                        or item.get("AnomalyScore", {}).get("MaxScore")
                        or 1.0
                    )
                    anomalies.append(
                        {
                            "provider": "aws",
                            "scope": "native",
                            "scope_key": scope_key,
                            "usage_date": item.get("AnomalyStartDate") or start.isoformat(),
                            "observed_cost": round(actual, 2),
                            "expected_cost": round(expected, 2),
                            "anomaly_score": self._normalize_anomaly_score(raw_score),
                            "metadata_json": {
                                "source": "aws_cost_anomaly_detection",
                                "monitor_arn": monitor_arn,
                                "monitor_name": monitor.get("MonitorName"),
                                "dimension": monitor.get("MonitorDimension"),
                                "impact_total": round(total_impact, 2),
                                "impact_percentage": float(impact.get("TotalImpactPercentage", 0.0) or 0.0),
                                "feedback": item.get("Feedback"),
                                "root_causes": root_causes,
                                "raw_anomaly_score": raw_score,
                            },
                        }
                    )
                next_token = response.get("NextPageToken")
                if not next_token:
                    break
        return anomalies

    def fetch_budget_recommendations(self) -> list[dict]:
        recommendations: list[dict] = []
        try:
            budgets = self.budgets.describe_budgets(AccountId=self.account_id, MaxResults=20).get("Budgets", [])
        except ClientError:
            return recommendations

        for budget in budgets:
            budget_name = budget.get("BudgetName", "AWS Budget")
            limit_amount = float(budget.get("BudgetLimit", {}).get("Amount", 0.0) or 0.0)
            spend = budget.get("CalculatedSpend", {})
            actual = float(spend.get("ActualSpend", {}).get("Amount", 0.0) or 0.0)
            forecast = float(spend.get("ForecastedSpend", {}).get("Amount", 0.0) or 0.0)
            if limit_amount <= 0:
                continue
            usage_ratio = max(actual, forecast) / limit_amount
            if usage_ratio < 0.8:
                continue
            recommendations.append(
                {
                    "provider": "aws",
                    "recommendation_type": "review_budget_threshold",
                    "resource_id": budget_name,
                    "description": f"Review AWS budget {budget_name}: {actual:.2f}/{limit_amount:.2f} USD consumed",
                    "estimated_monthly_savings": round(max(forecast - limit_amount, actual - limit_amount, 0.0), 2),
                    "action_payload": {
                        "action": "review_budget_threshold",
                        "resource_id": budget_name,
                        "source": "aws_budgets",
                        "budget_name": budget_name,
                        "budget_limit": limit_amount,
                        "actual_spend": actual,
                        "forecasted_spend": forecast,
                        "usage_ratio": round(usage_ratio, 4),
                    },
                }
            )
        return recommendations

    def fetch_native_signal_status(self, lookback_days: int) -> dict:
        summary = {
            "provider": "aws",
            "anomaly_monitor_count": 0,
            "active_native_anomaly_count": 0,
            "budget_count": 0,
            "budget_alert_count": 0,
            "compute_optimizer_status": "Unavailable",
            "trusted_advisor_available": False,
        }
        try:
            monitors = self.ce.get_anomaly_monitors(MaxResults=10).get("AnomalyMonitors", [])
            summary["anomaly_monitor_count"] = len(monitors)
            summary["active_native_anomaly_count"] = len(self.fetch_native_anomalies(lookback_days))
        except ClientError:
            pass

        try:
            budgets = self.budgets.describe_budgets(AccountId=self.account_id, MaxResults=20).get("Budgets", [])
            summary["budget_count"] = len(budgets)
            alert_count = 0
            for budget in budgets:
                limit_amount = float(budget.get("BudgetLimit", {}).get("Amount", 0.0) or 0.0)
                spend = budget.get("CalculatedSpend", {})
                actual = float(spend.get("ActualSpend", {}).get("Amount", 0.0) or 0.0)
                forecast = float(spend.get("ForecastedSpend", {}).get("Amount", 0.0) or 0.0)
                if limit_amount > 0 and max(actual, forecast) / limit_amount >= 0.8:
                    alert_count += 1
            summary["budget_alert_count"] = alert_count
        except ClientError:
            pass

        try:
            optimizer = self.compute_optimizer.get_enrollment_status()
            summary["compute_optimizer_status"] = optimizer.get("status", "Unknown")
        except ClientError:
            pass

        return summary

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

    def _metric_sum(
        self,
        namespace: str,
        metric_name: str,
        dimensions: list[dict],
        days: int = 7,
    ) -> float | None:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=days)
        datapoints = self.cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,
            Statistics=["Sum"],
        ).get("Datapoints", [])
        if not datapoints:
            return None
        values = [point["Sum"] for point in datapoints if "Sum" in point]
        return round(sum(values), 2) if values else None

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

    def _fetch_load_balancer_snapshots(self) -> list[dict]:
        snapshots: list[dict] = []
        try:
            load_balancers = self.elbv2.describe_load_balancers().get("LoadBalancers", [])
        except ClientError:
            return snapshots
        for lb in load_balancers:
            arn = lb["LoadBalancerArn"]
            requests = self._metric_sum(
                namespace="AWS/ApplicationELB",
                metric_name="RequestCount",
                dimensions=[{"Name": "LoadBalancer", "Value": arn.split("loadbalancer/")[-1]}],
            )
            state = lb.get("State", {}).get("Code")
            monthly_estimate = 16.2
            snapshots.append(
                {
                    "provider": "aws",
                    "account_id": self.account_id,
                    "project_id": None,
                    "resource_id": arn,
                    "resource_type": "load_balancer",
                    "region": self.region,
                    "state": state,
                    "cpu_utilization_avg": None,
                    "network_utilization_avg": requests,
                    "monthly_cost_estimate": monthly_estimate,
                    "is_idle": bool(state == "active" and (requests or 0) < 10),
                    "metadata_json": {
                        "name": lb.get("LoadBalancerName"),
                        "type": lb.get("Type"),
                        "scheme": lb.get("Scheme"),
                        "created_time": lb.get("CreatedTime").isoformat() if lb.get("CreatedTime") else None,
                        "vpc_id": lb.get("VpcId"),
                        "availability_zones": lb.get("AvailabilityZones", []),
                        "cost_source": "heuristic",
                    },
                }
            )
        return snapshots

    def _fetch_nat_gateway_snapshots(self) -> list[dict]:
        snapshots: list[dict] = []
        try:
            nat_gateways = self.ec2.describe_nat_gateways().get("NatGateways", [])
        except ClientError:
            return snapshots
        for gateway in nat_gateways:
            nat_id = gateway["NatGatewayId"]
            bytes_out = self._metric_sum(
                namespace="AWS/NATGateway",
                metric_name="BytesOutToDestination",
                dimensions=[{"Name": "NatGatewayId", "Value": nat_id}],
            )
            snapshots.append(
                {
                    "provider": "aws",
                    "account_id": self.account_id,
                    "project_id": None,
                    "resource_id": nat_id,
                    "resource_type": "nat_gateway",
                    "region": self.region,
                    "state": gateway.get("State"),
                    "cpu_utilization_avg": None,
                    "network_utilization_avg": bytes_out,
                    "monthly_cost_estimate": round(0.045 * 24 * 30, 2),
                    "is_idle": bool(gateway.get("State") == "available" and (bytes_out or 0) < 104857600),
                    "metadata_json": {
                        "subnet_id": gateway.get("SubnetId"),
                        "vpc_id": gateway.get("VpcId"),
                        "public_ips": [item.get("PublicIp") for item in gateway.get("NatGatewayAddresses", [])],
                        "create_time": gateway.get("CreateTime").isoformat() if gateway.get("CreateTime") else None,
                        "delete_time": gateway.get("DeleteTime").isoformat() if gateway.get("DeleteTime") else None,
                        "tags": gateway.get("Tags", []),
                        "cost_source": "heuristic",
                    },
                }
            )
        return snapshots

    def _fetch_snapshot_snapshots(self) -> list[dict]:
        snapshots: list[dict] = []
        try:
            snapshot_rows = self.ec2.describe_snapshots(OwnerIds=["self"]).get("Snapshots", [])
        except ClientError:
            return snapshots
        for snapshot in snapshot_rows:
            started_at = snapshot.get("StartTime")
            age_days = None
            if started_at:
                age_days = (datetime.now(timezone.utc) - started_at).days
            monthly_estimate = round(float(snapshot.get("VolumeSize", 0)) * 0.05, 2)
            snapshots.append(
                {
                    "provider": "aws",
                    "account_id": self.account_id,
                    "project_id": None,
                    "resource_id": snapshot["SnapshotId"],
                    "resource_type": "ebs_snapshot",
                    "region": self.region,
                    "state": snapshot.get("State"),
                    "cpu_utilization_avg": None,
                    "network_utilization_avg": None,
                    "monthly_cost_estimate": monthly_estimate,
                    "is_idle": bool((age_days or 0) >= 30),
                    "metadata_json": {
                        "volume_id": snapshot.get("VolumeId"),
                        "volume_size": snapshot.get("VolumeSize"),
                        "description": snapshot.get("Description"),
                        "start_time": started_at.isoformat() if started_at else None,
                        "age_days": age_days,
                        "tags": snapshot.get("Tags", []),
                        "cost_source": "heuristic",
                    },
                }
            )
        return snapshots

    def _fetch_rds_snapshots(self) -> list[dict]:
        snapshots: list[dict] = []
        try:
            db_instances = self.rds.describe_db_instances().get("DBInstances", [])
        except ClientError:
            return snapshots
        for db in db_instances:
            db_id = db["DBInstanceIdentifier"]
            cpu_avg = self._metric_average(
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                statistic="Average",
            )
            connections = self._metric_average(
                namespace="AWS/RDS",
                metric_name="DatabaseConnections",
                dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}],
                statistic="Average",
            )
            monthly_estimate = self._estimate_rds_monthly_cost(db.get("DBInstanceClass"), db.get("Engine"))
            snapshots.append(
                {
                    "provider": "aws",
                    "account_id": self.account_id,
                    "project_id": None,
                    "resource_id": db_id,
                    "resource_type": "rds_instance",
                    "region": self.region,
                    "state": db.get("DBInstanceStatus"),
                    "cpu_utilization_avg": cpu_avg,
                    "network_utilization_avg": connections,
                    "monthly_cost_estimate": monthly_estimate,
                    "is_idle": bool(db.get("DBInstanceStatus") == "available" and (cpu_avg or 0) < 5 and (connections or 0) < 2),
                    "metadata_json": {
                        "engine": db.get("Engine"),
                        "db_instance_class": db.get("DBInstanceClass"),
                        "allocated_storage": db.get("AllocatedStorage"),
                        "multi_az": db.get("MultiAZ"),
                        "storage_type": db.get("StorageType"),
                        "tags": [],
                        "cost_source": "heuristic",
                    },
                }
            )
        return snapshots

    def _normalize_anomaly_score(self, value: float | int | None) -> float:
        raw = float(value or 0.0)
        if raw <= 0:
            return 0.5
        if raw <= 1:
            return raw
        return min(raw / 100.0, 1.0)

    def _estimate_rds_monthly_cost(self, db_instance_class: str | None, engine: str | None) -> float:
        if not db_instance_class:
            return 0.0
        family_price = {
            "db.t3.micro": 0.021,
            "db.t3.small": 0.042,
            "db.t3.medium": 0.084,
            "db.t4g.micro": 0.019,
            "db.t4g.small": 0.038,
            "db.t4g.medium": 0.076,
        }.get(db_instance_class, 0.12)
        return round(family_price * 24 * 30, 2)

    @staticmethod
    def _stopped_since(state_transition_reason: str | None) -> str | None:
        if not state_transition_reason:
            return None
        match = re.search(r"\(([^)]+)\)", state_transition_reason)
        if not match:
            return None
        timestamp = match.group(1).replace(" GMT", "")
        for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(timestamp, fmt)
                return parsed.replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                continue
        return None
