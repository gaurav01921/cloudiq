from datetime import date, timedelta

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.models import Anomaly, AuditLog, CostRecord, JobRun, Recommendation, ResourceSnapshot, User
from app.services.anomaly_detection import AnomalyDetectionService
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.cost_intelligence import CostIntelligenceService
from app.services.demo_data import DemoDataService
from app.services.ingestion import IngestionService
from app.services.invite import InviteService
from app.services.job_monitor import JobMonitorService
from app.services.optimization import OptimizationService
from app.services.recommendations import RecommendationService
from app.services.runtime_settings import RuntimeSettingsService
from app.schemas.api import OptimizationRequest


def build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_anomaly_detection_flags_spike() -> None:
    db = build_session()
    start = date(2026, 1, 1)
    baseline = [5, 5, 6, 5, 6, 5, 5, 6, 5, 5, 6, 5, 6, 5, 5, 6, 5, 5, 6, 30]
    for offset, amount in enumerate(baseline):
        db.add(
            CostRecord(
                provider="aws",
                account_id="123456789012",
                project_id=None,
                service="Amazon Elastic Compute Cloud - Compute",
                resource_id="aggregated",
                usage_date=start + timedelta(days=offset),
                cost_amount=amount,
                currency="USD",
                usage_quantity=float(amount),
                usage_unit="Hrs",
                metadata_json={},
            )
        )
    db.commit()

    created = AnomalyDetectionService(db).run()

    assert created >= 1


def test_anomaly_detection_clears_stale_rows_when_not_enough_history() -> None:
    db = build_session()
    db.add(
        Anomaly(
            provider="demo",
            scope="provider",
            scope_key="demo:all-services",
            usage_date="2026-03-01",
            observed_cost=20.0,
            expected_cost=10.0,
            anomaly_score=0.9,
            metadata_json={},
        )
    )
    db.commit()

    created = AnomalyDetectionService(db).run()

    assert created == 0
    assert db.query(Anomaly).count() == 0


def test_recommendations_include_idle_aws_resources() -> None:
    db = build_session()
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="i-abc123",
            resource_type="ec2_instance",
            region="us-east-1",
            state="running",
            cpu_utilization_avg=1.0,
            network_utilization_avg=100.0,
            monthly_cost_estimate=12.0,
            is_idle=True,
            metadata_json={"instance_type": "t3.micro"},
        )
    )
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="vol-abc123",
            resource_type="ebs_volume",
            region="us-east-1",
            state="available",
            cpu_utilization_avg=None,
            network_utilization_avg=None,
            monthly_cost_estimate=7.5,
            is_idle=True,
            metadata_json={"size_gb": 100},
        )
    )
    db.commit()

    created = RecommendationService(db).generate()

    assert created == 2


def test_recommendations_cover_underutilized_instances_and_unattached_eips() -> None:
    db = build_session()
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="i-under123",
            resource_type="ec2_instance",
            region="us-east-1",
            state="running",
            cpu_utilization_avg=12.0,
            network_utilization_avg=500.0,
            monthly_cost_estimate=30.0,
            is_idle=False,
            metadata_json={"instance_type": "t3.small", "tags": []},
        )
    )
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="eipalloc-123",
            resource_type="elastic_ip",
            region="us-east-1",
            state="unattached",
            cpu_utilization_avg=None,
            network_utilization_avg=None,
            monthly_cost_estimate=3.6,
            is_idle=True,
            metadata_json={"public_ip": "203.0.113.10", "association_id": None, "tags": []},
        )
    )
    db.commit()

    created = RecommendationService(db).generate()

    assert created == 2
    rec_types = {rec.recommendation_type for rec in db.query(Recommendation).all()}
    assert "release_unattached_eip" in rec_types
    assert "rightsize_underutilized_instance" in rec_types


def test_recommendations_cover_stopped_instances_snapshots_nat_and_rds() -> None:
    db = build_session()
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="i-stopped123",
            resource_type="ec2_instance",
            region="us-east-1",
            state="stopped",
            cpu_utilization_avg=0.0,
            network_utilization_avg=0.0,
            monthly_cost_estimate=15.0,
            is_idle=False,
            metadata_json={"stopped_since": "2026-03-01T00:00:00+00:00", "tags": []},
        )
    )
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="snap-123",
            resource_type="ebs_snapshot",
            region="us-east-1",
            state="completed",
            cpu_utilization_avg=None,
            network_utilization_avg=None,
            monthly_cost_estimate=6.0,
            is_idle=True,
            metadata_json={"age_days": 45, "tags": []},
        )
    )
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="nat-123",
            resource_type="nat_gateway",
            region="us-east-1",
            state="available",
            cpu_utilization_avg=None,
            network_utilization_avg=1000.0,
            monthly_cost_estimate=32.4,
            is_idle=True,
            metadata_json={},
        )
    )
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="db-123",
            resource_type="rds_instance",
            region="us-east-1",
            state="available",
            cpu_utilization_avg=2.0,
            network_utilization_avg=1.0,
            monthly_cost_estimate=60.0,
            is_idle=True,
            metadata_json={},
        )
    )
    db.commit()

    created = RecommendationService(db).generate()

    assert created >= 4
    rec_types = {rec.recommendation_type for rec in db.query(Recommendation).all()}
    assert "review_long_stopped_instance" in rec_types
    assert "review_old_snapshot" in rec_types
    assert "review_idle_nat_gateway" in rec_types
    assert "review_idle_rds_instance" in rec_types


def test_demo_recommendations_keep_demo_provider_for_simulated_execution() -> None:
    db = build_session()
    db.add(
        ResourceSnapshot(
            provider="demo",
            account_id="demo-account",
            project_id=None,
            resource_id="demo-i-001",
            resource_type="ec2_instance",
            region="demo-region-1",
            state="running",
            cpu_utilization_avg=1.0,
            network_utilization_avg=50.0,
            monthly_cost_estimate=18.0,
            is_idle=True,
            metadata_json={"tags": []},
        )
    )
    db.commit()

    RecommendationService(db).generate()
    recommendation = db.query(Recommendation).one()

    assert recommendation.provider == "demo"


def test_native_provider_recommendations_are_ingested() -> None:
    db = build_session()
    original_method = RecommendationService._generate_native_provider_recommendations
    try:
        RecommendationService._generate_native_provider_recommendations = lambda self: (
            self.db.add(
                Recommendation(
                    provider="aws",
                    recommendation_type="native_rightsize_instance",
                    resource_id="i-native123",
                    description="AWS native recommendation",
                    estimated_monthly_savings=12.5,
                    action_payload={"action": "review_native_recommendation", "resource_id": "i-native123"},
                )
            ) or 1
        )
        created = RecommendationService(db).generate()
    finally:
        RecommendationService._generate_native_provider_recommendations = original_method

    assert created == 1
    recommendation = db.query(Recommendation).one()
    assert recommendation.recommendation_type == "native_rightsize_instance"


def test_anomalies_generate_advisory_recommendations() -> None:
    db = build_session()
    db.add(
        Anomaly(
            provider="demo",
            scope="service",
            scope_key="Amazon Elastic Compute Cloud - Compute",
            usage_date="2026-03-25",
            observed_cost=22.2,
            expected_cost=13.2,
            anomaly_score=1.0,
            metadata_json={"delta": 9.0},
        )
    )
    db.commit()

    created = RecommendationService(db).generate()

    assert created == 1
    recommendation = db.query(Recommendation).one()
    assert recommendation.provider == "demo"
    assert recommendation.recommendation_type == "review_compute_cost_anomaly"
    assert recommendation.action_payload["action"] == "review_compute_anomaly"


def test_demo_anomaly_recommendation_executes_in_simulation_mode() -> None:
    db = build_session()
    db.add(
        Recommendation(
            provider="demo",
            recommendation_type="review_compute_cost_anomaly",
            resource_id="Amazon Elastic Compute Cloud - Compute",
            description="Review EC2 spend anomaly",
            estimated_monthly_savings=9.0,
            approved=True,
            action_payload={
                "action": "review_compute_anomaly",
                "resource_id": "Amazon Elastic Compute Cloud - Compute",
                "anomaly_scope_key": "Amazon Elastic Compute Cloud - Compute",
                "suspected_overage": 9.0,
                "anomaly_score": 1.0,
            },
        )
    )
    db.commit()

    result = OptimizationService(db).execute(OptimizationRequest(recommendation_ids=[1], force_execute=True))

    assert result[0].executed is True
    assert result[0].result["simulated"] is True


def test_demo_approve_only_returns_dry_run_ready_without_executing() -> None:
    db = build_session()
    db.add(
        Recommendation(
            provider="demo",
            recommendation_type="stop_idle_instance",
            resource_id="demo-i-001",
            description="Stop idle demo instance",
            estimated_monthly_savings=18.0,
            approved=False,
            action_payload={
                "action": "stop_instance",
                "resource_id": "demo-i-001",
            },
        )
    )
    db.commit()

    result = OptimizationService(db).execute(OptimizationRequest(recommendation_ids=[1], auto_approve=True))
    recommendation = db.query(Recommendation).get(1)

    assert result[0].executed is False
    assert result[0].result["dry_run"] is True
    assert result[0].result["authorized"] is True
    assert recommendation.approved is True
    assert recommendation.executed is False


def test_aws_dry_run_does_not_mark_recommendation_executed() -> None:
    db = build_session()
    recommendation = Recommendation(
        provider="aws",
        recommendation_type="stop_idle_instance",
        resource_id="i-1234567890",
        description="Stop idle EC2 instance i-1234567890",
        estimated_monthly_savings=7.0,
        approved=False,
        action_payload={
            "action": "stop_instance",
            "resource_id": "i-1234567890",
            "safety_context": {"state": "running", "tags": []},
        },
    )
    db.add(recommendation)
    db.commit()

    original_enabled = get_settings().aws_enabled
    get_settings().aws_enabled = False
    try:
        result = OptimizationService(db).execute(OptimizationRequest(recommendation_ids=[1], auto_approve=True))
    finally:
        get_settings().aws_enabled = original_enabled

    updated = db.query(Recommendation).get(1)
    assert result[0].executed is False
    assert updated.executed is False


def test_force_execution_requires_prior_dry_run() -> None:
    db = build_session()
    db.add(
        Recommendation(
            provider="gcp",
            recommendation_type="stop_idle_instance",
            resource_id="i-safe123",
            description="Stop idle EC2 instance i-safe123",
            estimated_monthly_savings=8.0,
            approved=True,
            action_payload={
                "action": "stop_instance",
                "resource_id": "i-safe123",
                "safety_context": {"state": "running", "tags": []},
            },
        )
    )
    db.commit()

    result = OptimizationService(db).execute(
        OptimizationRequest(recommendation_ids=[1], force_execute=True)
    )

    assert result[0].executed is False
    assert "successful prior dry run" in result[0].result["reason"]


def test_protected_tags_block_execution() -> None:
    db = build_session()
    settings = get_settings()
    original_keys = settings.optimization_protected_tag_keys
    original_values = settings.optimization_protected_tag_values
    original_root_block = settings.optimization_block_root_credentials
    settings.optimization_protected_tag_keys = "Protected"
    settings.optimization_protected_tag_values = "true"
    settings.optimization_block_root_credentials = False
    try:
        db.add(
            Recommendation(
                provider="gcp",
                recommendation_type="stop_idle_instance",
                resource_id="i-protected123",
                description="Stop idle EC2 instance i-protected123",
                estimated_monthly_savings=8.0,
                approved=True,
                execution_result={"dry_run": True, "authorized": True},
                action_payload={
                    "action": "stop_instance",
                    "resource_id": "i-protected123",
                    "safety_context": {
                        "state": "running",
                        "tags": [{"Key": "Protected", "Value": "true"}],
                    },
                },
            )
        )
        db.commit()

        result = OptimizationService(db).execute(
            OptimizationRequest(recommendation_ids=[1], force_execute=True)
        )

        assert result[0].executed is False
        assert "protected by tag" in result[0].result["reason"]
    finally:
        settings.optimization_protected_tag_keys = original_keys
        settings.optimization_protected_tag_values = original_values
        settings.optimization_block_root_credentials = original_root_block


def test_password_hashing_round_trip() -> None:
    encoded = hash_password("SecretPass123!")
    assert verify_password("SecretPass123!", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_bootstrap_admin_is_created() -> None:
    db = build_session()
    settings = get_settings()
    original_email = settings.bootstrap_admin_email
    original_password = settings.bootstrap_admin_password
    original_name = settings.bootstrap_admin_name
    settings.bootstrap_admin_email = "admin@test.local"
    settings.bootstrap_admin_password = "AdminPass123!"
    settings.bootstrap_admin_name = "Admin Tester"
    try:
        AuthService(db).ensure_bootstrap_admin()
        user = db.query(User).filter(User.email == "admin@test.local").one()
        assert user.role == "admin"
        assert verify_password("AdminPass123!", user.password_hash) is True
    finally:
        settings.bootstrap_admin_email = original_email
        settings.bootstrap_admin_password = original_password
        settings.bootstrap_admin_name = original_name


def test_invite_create_and_accept_flow() -> None:
    db = build_session()
    admin = User(
        email="admin@example.com",
        full_name="Admin",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    invite = InviteService(db).create_invite(
        email="viewer@example.com",
        full_name="Viewer User",
        role="viewer",
        invited_by=admin,
        expires_in_days=3,
    )
    user = InviteService(db).accept_invite(token=invite.token, password="ViewerPass123!", full_name=None)

    assert user.email == "viewer@example.com"
    assert user.role == "viewer"


def test_audit_log_records_action() -> None:
    db = build_session()
    admin = User(
        email="admin@example.com",
        full_name="Admin",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    entry = AuditService(db).record(
        action="ops.sync",
        actor=admin,
        target_type="system",
        target_id="sync",
        details={"status": "ok"},
    )

    assert entry.action == "ops.sync"
    assert db.query(AuditLog).count() == 1


def test_audit_log_filtering_supports_action_and_query() -> None:
    db = build_session()
    admin = User(
        email="admin@example.com",
        full_name="Admin",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    audit_service = AuditService(db)
    audit_service.record(action="ops.sync", actor=admin, target_type="system", target_id="sync")
    audit_service.record(action="auth.login", actor=admin, target_type="user", target_id="1")

    filtered = audit_service.list_entries(action="ops.sync", query="sync")

    assert len(filtered) == 1
    assert filtered[0].action == "ops.sync"


def test_audit_log_purge_removes_matching_entries() -> None:
    db = build_session()
    admin = User(
        email="admin@example.com",
        full_name="Admin",
        password_hash=hash_password("AdminPass123!"),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    audit_service = AuditService(db)
    audit_service.record(action="ops.sync", actor=admin, outcome="success", target_type="system", target_id="sync")
    audit_service.record(action="auth.login", actor=admin, outcome="success", target_type="user", target_id="1")

    deleted_count = audit_service.purge_entries(action="ops.sync")

    assert deleted_count == 1
    assert db.query(AuditLog).count() == 1


def test_demo_data_service_generates_records_and_snapshots() -> None:
    service = DemoDataService(lookback_days=10)
    records = service.generate_cost_records()
    snapshots = service.generate_resource_snapshots()
    assert len(records) >= 10
    assert len(snapshots) >= 2
    assert all(record["provider"] == "demo" for record in records)


def test_job_monitor_records_lifecycle() -> None:
    db = build_session()
    monitor = JobMonitorService(db)
    run = monitor.start("sync")
    monitor.finish(run, "success", {"records": 10})
    latest = monitor.latest()
    assert len(latest) == 1
    assert latest[0].status == "success"
    assert latest[0].details_json == {"records": 10}


def test_anomaly_status_includes_sync_markers() -> None:
    db = build_session()
    monitor = JobMonitorService(db)
    run = monitor.start("cloud-cost-sync")
    monitor.finish(run, "success", {"ingested_cost_records": 9, "anomalies_detected": 1})

    status = CostIntelligenceService(db).get_anomaly_status()

    assert len(status.sync_markers) == 1
    assert status.sync_markers[0].records_ingested == 9


def test_anomaly_status_waits_for_real_cost_signal() -> None:
    db = build_session()
    start = date(2026, 3, 1)
    for offset in range(10):
        db.add(
            CostRecord(
                provider="aws",
                account_id="123456789012",
                project_id=None,
                service="AWS Glue",
                resource_id="aggregated",
                usage_date=start + timedelta(days=offset),
                cost_amount=0.0,
                currency="USD",
                usage_quantity=0.0,
                usage_unit="Hrs",
                metadata_json={},
            )
        )
    db.commit()

    status = CostIntelligenceService(db).get_anomaly_status()

    assert status.readiness == "waiting_for_cost_signal"
    assert status.signal_days == 0


def test_dashboard_summary_separates_billed_spend_from_run_rate() -> None:
    db = build_session()
    db.add(
        ResourceSnapshot(
            provider="aws",
            account_id="123456789012",
            project_id=None,
            resource_id="i-live123",
            resource_type="ec2_instance",
            region="eu-north-1",
            state="running",
            cpu_utilization_avg=3.0,
            network_utilization_avg=120.0,
            monthly_cost_estimate=13.68,
            is_idle=False,
            metadata_json={},
        )
    )
    start = date(2026, 3, 1)
    for offset in range(5):
        db.add(
            CostRecord(
                provider="aws",
                account_id="123456789012",
                project_id=None,
                service="AWS Glue",
                resource_id="aggregated",
                usage_date=start + timedelta(days=offset),
                cost_amount=0.0,
                currency="USD",
                usage_quantity=0.0,
                usage_unit="Hrs",
                metadata_json={},
            )
        )
    db.commit()

    summary = CostIntelligenceService(db).get_dashboard_summary()

    assert summary.actual_billed_cost == 0.0
    assert summary.total_cost == 0.0
    assert summary.estimated_monthly_run_rate == 13.68
    assert summary.projected_end_of_month_cost == 13.68
    assert summary.has_actual_billing_data is False
    assert summary.billing_signal_status == "billing_zero_or_credit_only"


def test_runtime_data_mode_can_be_overridden() -> None:
    db = build_session()
    service = RuntimeSettingsService(db)

    service.set_data_mode("demo")

    assert service.get_data_mode() == "demo"


def test_ingestion_clears_inactive_provider_data_when_mode_changes() -> None:
    db = build_session()
    db.add(
        CostRecord(
            provider="demo",
            account_id="demo-account",
            project_id=None,
            service="Amazon Elastic Compute Cloud - Compute",
            resource_id="aggregated",
            usage_date=date(2026, 3, 1),
            cost_amount=10.0,
            currency="USD",
            usage_quantity=24.0,
            usage_unit="Hrs",
            metadata_json={},
        )
    )
    db.add(
        ResourceSnapshot(
            provider="demo",
            account_id="demo-account",
            project_id=None,
            resource_id="demo-i-001",
            resource_type="ec2_instance",
            region="demo-region-1",
            state="running",
            cpu_utilization_avg=1.0,
            network_utilization_avg=20.0,
            monthly_cost_estimate=12.0,
            is_idle=True,
            metadata_json={},
        )
    )
    db.commit()

    settings = get_settings()
    original_aws_enabled = settings.aws_enabled
    original_gcp_enabled = settings.gcp_enabled
    settings.aws_enabled = False
    settings.gcp_enabled = False
    try:
        RuntimeSettingsService(db).set_data_mode("live")
        IngestionService(db).ingest()

        assert db.query(CostRecord).filter(CostRecord.provider == "demo").count() == 0
        assert db.query(ResourceSnapshot).filter(ResourceSnapshot.provider == "demo").count() == 0
    finally:
        settings.aws_enabled = original_aws_enabled
        settings.gcp_enabled = original_gcp_enabled
