from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobRun


class JobMonitorService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def start(self, job_name: str, details: dict | None = None) -> JobRun:
        run = JobRun(job_name=job_name, status="running", details_json=details or {})
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def finish(self, run: JobRun, status: str, details: dict | None = None) -> JobRun:
        run.status = status
        run.finished_at = datetime.utcnow()
        run.details_json = details or run.details_json
        self.db.commit()
        self.db.refresh(run)
        return run

    def latest(self, limit: int = 50) -> list[JobRun]:
        return self.db.execute(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)).scalars().all()
