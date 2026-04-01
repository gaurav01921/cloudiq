from datetime import datetime

from pydantic import BaseModel


class SyncResponse(BaseModel):
    ingested_cost_records: int
    ingested_resource_snapshots: int
    anomalies_detected: int
    recommendations_generated: int


class DashboardSummaryResponse(BaseModel):
    total_cost: float
    actual_billed_cost: float
    estimated_monthly_run_rate: float
    projected_end_of_month_cost: float
    cost_source: str
    billing_signal_status: str
    has_actual_billing_data: bool
    signal_days: int
    data_mode: str
    anomaly_count: int
    recommendation_count: int
    estimated_monthly_savings: float
    last_sync_at: datetime | None


class AnomalyStatusPoint(BaseModel):
    usage_date: str
    record_count: int
    total_cost: float
    point_source: str


class SyncTimelinePoint(BaseModel):
    started_at: datetime
    status: str
    records_ingested: int
    anomalies_detected: int


class AnomalyStatusResponse(BaseModel):
    readiness: str
    status_message: str
    min_days_required: int
    observed_days: int
    signal_days: int
    latest_detection_run_at: datetime | None
    timeline_mode: str
    points: list[AnomalyStatusPoint]
    sync_markers: list[SyncTimelinePoint]


class AnomalyResponse(BaseModel):
    id: int
    provider: str
    scope: str
    scope_key: str
    detected_at: datetime
    usage_date: str
    observed_cost: float
    expected_cost: float
    anomaly_score: float
    metadata_json: dict | None

    class Config:
        from_attributes = True


class RecommendationResponse(BaseModel):
    id: int
    provider: str
    recommendation_type: str
    resource_id: str
    description: str
    estimated_monthly_savings: float
    approved: bool
    executed: bool
    execution_result: dict | None

    class Config:
        from_attributes = True


class OptimizationRequest(BaseModel):
    recommendation_ids: list[int] | None = None
    auto_approve: bool = False
    force_execute: bool = False
    bypass_safety_checks: bool = False


class OptimizationExecutionResponse(BaseModel):
    recommendation_id: int
    executed: bool
    result: dict


class JobRunResponse(BaseModel):
    id: int
    job_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    details_json: dict | None

    class Config:
        from_attributes = True


class DataModeResponse(BaseModel):
    data_mode: str


class DataModeUpdateRequest(BaseModel):
    data_mode: str


class DashboardSettingsResponse(BaseModel):
    full_name: str
    email: str
    role: str
    theme: str
    gemini_api_key_configured: bool
    gemini_api_key_hint: str | None = None


class DashboardSettingsUpdateRequest(BaseModel):
    theme: str | None = None
    gemini_api_key: str | None = None
    clear_gemini_api_key: bool = False


class NativeSignalStatusResponse(BaseModel):
    provider: str
    anomaly_monitor_count: int
    active_native_anomaly_count: int
    budget_count: int
    budget_alert_count: int
    compute_optimizer_status: str
    trusted_advisor_available: bool
