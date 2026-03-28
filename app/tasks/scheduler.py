from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.alerts import AlertService
from app.services.cost_intelligence import CostIntelligenceService
from app.services.job_monitor import JobMonitorService

logger = get_logger(__name__)

class SchedulerService:
    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.started = False
        settings = get_settings()
        self.scheduler.add_job(
            self._sync_job,
            "cron",
            minute=settings.scheduler_cron_minute,
            id="cloud-cost-sync",
            replace_existing=True,
        )

    def start(self) -> None:
        if not self.started:
            self.scheduler.start()
            self.started = True

    def stop(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    @staticmethod
    def _sync_job() -> None:
        db = SessionLocal()
        monitor = JobMonitorService(db)
        run = monitor.start("cloud-cost-sync")
        try:
            result = CostIntelligenceService(db).sync()
            monitor.finish(run, "success", details=result.model_dump())
            logger.info({"event": "job_run", "job_name": "cloud-cost-sync", "status": "success", "details": result.model_dump()})
        finally:
            if run.status == "running":
                details = {"error": "Unexpected scheduler termination."}
                monitor.finish(run, "failed", details=details)
                if get_settings().alert_on_job_failure:
                    AlertService().send("job_failure", "error", {"job_name": "cloud-cost-sync", **details})
            db.close()


scheduler_service = SchedulerService()
