from functools import lru_cache
from pathlib import Path
import tempfile

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_database_url() -> str:
    db_dir = Path(tempfile.gettempdir()) / "cloud-cost-intelligence"
    db_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(db_dir / 'cloud_cost_intelligence.db').as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Cloud Cost Intelligence", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    database_url: str = Field(default_factory=default_database_url, alias="DATABASE_URL")
    data_mode: str = Field(default="live", alias="DATA_MODE")
    default_currency: str = Field(default="USD", alias="DEFAULT_CURRENCY")
    session_secret_key: str = Field(default="change-me-session-secret", alias="SESSION_SECRET_KEY")
    bootstrap_admin_email: str = Field(default="admin@example.com", alias="BOOTSTRAP_ADMIN_EMAIL")
    bootstrap_admin_password: str = Field(default="ChangeMe123!", alias="BOOTSTRAP_ADMIN_PASSWORD")
    bootstrap_admin_name: str = Field(default="Platform Admin", alias="BOOTSTRAP_ADMIN_NAME")
    app_base_url: str = Field(default="http://127.0.0.1:8000", alias="APP_BASE_URL")

    aws_enabled: bool = Field(default=True, alias="AWS_ENABLED")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_account_id: str | None = Field(default=None, alias="AWS_ACCOUNT_ID")
    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    aws_session_token: str | None = Field(default=None, alias="AWS_SESSION_TOKEN")
    aws_cost_anomaly_threshold: float = Field(default=0.98, alias="AWS_COST_ANOMALY_THRESHOLD")

    gcp_enabled: bool = Field(default=True, alias="GCP_ENABLED")
    gcp_project_id: str | None = Field(default=None, alias="GCP_PROJECT_ID")
    gcp_billing_export_table: str | None = Field(default=None, alias="GCP_BILLING_EXPORT_TABLE")
    gcp_cost_anomaly_threshold: float = Field(default=0.98, alias="GCP_COST_ANOMALY_THRESHOLD")

    optimization_dry_run: bool = Field(default=True, alias="OPTIMIZATION_DRY_RUN")
    optimization_min_monthly_savings: float = Field(default=5.0, alias="OPTIMIZATION_MIN_MONTHLY_SAVINGS")
    optimization_require_explicit_approval: bool = Field(default=True, alias="OPTIMIZATION_REQUIRE_EXPLICIT_APPROVAL")
    optimization_max_actions_per_run: int = Field(default=3, alias="OPTIMIZATION_MAX_ACTIONS_PER_RUN")
    optimization_block_root_credentials: bool = Field(default=True, alias="OPTIMIZATION_BLOCK_ROOT_CREDENTIALS")
    optimization_protected_tag_keys: str = Field(
        default="DoNotStop,DoNotDelete,Protected,Critical,Production",
        alias="OPTIMIZATION_PROTECTED_TAG_KEYS",
    )
    optimization_protected_tag_values: str = Field(
        default="true,yes,1,prod,production,critical",
        alias="OPTIMIZATION_PROTECTED_TAG_VALUES",
    )
    ingestion_lookback_days: int = Field(default=30, alias="INGESTION_LOOKBACK_DAYS")
    retry_attempts: int = Field(default=3, alias="RETRY_ATTEMPTS")
    retry_base_delay_seconds: float = Field(default=1.0, alias="RETRY_BASE_DELAY_SECONDS")
    alerting_enabled: bool = Field(default=False, alias="ALERTING_ENABLED")
    alerting_webhook_url: str | None = Field(default=None, alias="ALERTING_WEBHOOK_URL")
    alert_on_job_failure: bool = Field(default=True, alias="ALERT_ON_JOB_FAILURE")
    alert_on_anomaly_detected: bool = Field(default=False, alias="ALERT_ON_ANOMALY_DETECTED")
    structured_logs: bool = Field(default=True, alias="STRUCTURED_LOGS")

    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")
    scheduler_cron_minute: int = Field(default=15, alias="SCHEDULER_CRON_MINUTE")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
