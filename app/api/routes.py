from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.auth_routes import current_user, require_operator
from app.db.session import SessionLocal
from app.db.session import get_db
from app.models import User
from app.schemas.api import (
    AnomalyResponse,
    AnomalyStatusResponse,
    DashboardSettingsResponse,
    DashboardSettingsUpdateRequest,
    DashboardSummaryResponse,
    DataModeResponse,
    DataModeUpdateRequest,
    JobRunResponse,
    OptimizationExecutionResponse,
    OptimizationRequest,
    RecommendationResponse,
    SyncResponse,
)
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.services.cost_intelligence import CostIntelligenceService
from app.services.job_monitor import JobMonitorService
from app.services.runtime_settings import RuntimeSettingsService
from app.services.topology import TopologyService

router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@router.get("/", include_in_schema=False, response_model=None)
def dashboard(request: Request) -> Response:
    if "user_id" not in request.session:
        return RedirectResponse(url="/auth/login", status_code=303)
    db = SessionLocal()
    try:
        AuthService(db).get_current_user(request)
    except HTTPException:
        request.session.clear()
        return RedirectResponse(url="/auth/login", status_code=303)
    finally:
        db.close()
    index_path = STATIC_DIR / "index.html"
    styles_version = int((STATIC_DIR / "styles.css").stat().st_mtime)
    app_version = int((STATIC_DIR / "app.js").stat().st_mtime)
    html = index_path.read_text(encoding="utf-8")
    html = (
        html
        .replace("__STYLES_VERSION__", str(styles_version))
        .replace("__APP_VERSION__", str(app_version))
    )
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/architecture")
def get_architecture(_: User = Depends(current_user)) -> dict:
    return TopologyService().describe()


@router.post("/sync", response_model=SyncResponse)
def sync_cost_data(
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> SyncResponse:
    service = CostIntelligenceService(db)
    result = service.sync()
    AuditService(db).record(
        action="ops.sync",
        actor=user,
        target_type="system",
        target_id="sync",
        details=result.model_dump(),
    )
    return result


@router.get("/anomalies", response_model=list[AnomalyResponse])
def get_anomalies(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[AnomalyResponse]:
    service = CostIntelligenceService(db)
    return service.list_anomalies()


@router.get("/anomaly-status", response_model=AnomalyStatusResponse)
def get_anomaly_status(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> AnomalyStatusResponse:
    service = CostIntelligenceService(db)
    return service.get_anomaly_status()


@router.get("/summary", response_model=DashboardSummaryResponse)
def get_summary(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    service = CostIntelligenceService(db)
    return service.get_dashboard_summary()


@router.get("/data-mode", response_model=DataModeResponse)
def get_data_mode(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DataModeResponse:
    return DataModeResponse(data_mode=RuntimeSettingsService(db).get_data_mode())


@router.get("/settings", response_model=DashboardSettingsResponse)
def get_dashboard_settings(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DashboardSettingsResponse:
    runtime = RuntimeSettingsService(db)
    gemini_api_key = runtime.get_gemini_api_key()
    return DashboardSettingsResponse(
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        theme=runtime.get_theme(),
        gemini_api_key_configured=bool(gemini_api_key),
        gemini_api_key_hint=runtime.mask_api_key(gemini_api_key),
    )


@router.put("/settings", response_model=DashboardSettingsResponse)
def update_dashboard_settings(
    payload: DashboardSettingsUpdateRequest,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> DashboardSettingsResponse:
    runtime = RuntimeSettingsService(db)

    if payload.theme is not None:
        runtime.set_theme(payload.theme)

    if payload.clear_gemini_api_key:
        runtime.clear_gemini_api_key()
    elif payload.gemini_api_key is not None:
        normalized = payload.gemini_api_key.strip()
        if normalized:
            runtime.set_gemini_api_key(normalized)

    gemini_api_key = runtime.get_gemini_api_key()
    AuditService(db).record(
        action="settings.dashboard.update",
        actor=user,
        target_type="system",
        target_id="dashboard_settings",
        details={
            "theme": runtime.get_theme(),
            "gemini_api_key_configured": bool(gemini_api_key),
            "gemini_api_key_cleared": payload.clear_gemini_api_key,
        },
    )
    return DashboardSettingsResponse(
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        theme=runtime.get_theme(),
        gemini_api_key_configured=bool(gemini_api_key),
        gemini_api_key_hint=runtime.mask_api_key(gemini_api_key),
    )


@router.put("/data-mode", response_model=DataModeResponse)
def update_data_mode(
    payload: DataModeUpdateRequest,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> DataModeResponse:
    data_mode = RuntimeSettingsService(db).set_data_mode(payload.data_mode)
    AuditService(db).record(
        action="settings.data_mode.update",
        actor=user,
        target_type="system",
        target_id="data_mode",
        details={"data_mode": data_mode},
    )
    return DataModeResponse(data_mode=data_mode)


@router.get("/recommendations", response_model=list[RecommendationResponse])
def get_recommendations(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[RecommendationResponse]:
    service = CostIntelligenceService(db)
    return service.list_recommendations()


@router.get("/job-runs", response_model=list[JobRunResponse])
def get_job_runs(
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[JobRunResponse]:
    return [JobRunResponse.model_validate(row) for row in JobMonitorService(db).latest()]


@router.post("/optimize", response_model=list[OptimizationExecutionResponse])
def run_optimizations(
    request: OptimizationRequest,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> list[OptimizationExecutionResponse]:
    service = CostIntelligenceService(db)
    result = service.execute_recommendations(request)
    AuditService(db).record(
        action="ops.optimize",
        actor=user,
        target_type="recommendation",
        target_id=",".join(str(item.recommendation_id) for item in result),
        details={"request": request.model_dump(), "results": [item.model_dump() for item in result]},
    )
    return result
