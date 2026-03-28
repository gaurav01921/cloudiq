from datetime import date, timedelta

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.base import Base
from app.models import AuditLog, CostRecord, Recommendation, ResourceSnapshot, User
from app.services.anomaly_detection import AnomalyDetectionService
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.invite import InviteService
from app.services.optimization import OptimizationService
from app.services.recommendations import RecommendationService
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
