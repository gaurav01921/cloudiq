from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.cost_intelligence import CostIntelligenceService


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
        try:
            CostIntelligenceService(db).sync()
        finally:
            db.close()


scheduler_service = SchedulerService()
