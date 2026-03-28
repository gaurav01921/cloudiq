from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import AuditLog, User


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        action: str,
        outcome: str = "success",
        actor: User | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict | None = None,
        commit: bool = True,
    ) -> AuditLog:
        entry = AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_email=actor.email if actor else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            details_json=details,
        )
        self.db.add(entry)
        if commit:
            self.db.commit()
            self.db.refresh(entry)
        return entry

    def list_entries(
        self,
        *,
        query: str | None = None,
        action: str | None = None,
        outcome: str | None = None,
        actor_email: str | None = None,
        limit: int = 100,
    ) -> list[AuditLog]:
        statement = select(AuditLog)

        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    AuditLog.action.ilike(pattern),
                    AuditLog.actor_email.ilike(pattern),
                    AuditLog.target_type.ilike(pattern),
                    AuditLog.target_id.ilike(pattern),
                )
            )
        if action:
            statement = statement.where(AuditLog.action == action)
        if outcome:
            statement = statement.where(AuditLog.outcome == outcome)
        if actor_email:
            statement = statement.where(AuditLog.actor_email == actor_email)

        statement = statement.order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 500)))
        return self.db.execute(statement).scalars().all()

    def purge_entries(
        self,
        *,
        older_than_days: int | None = None,
        action: str | None = None,
        outcome: str | None = None,
        actor_email: str | None = None,
        query: str | None = None,
    ) -> int:
        statement = delete(AuditLog)

        if older_than_days is not None:
            cutoff = datetime.utcnow() - timedelta(days=max(0, older_than_days))
            statement = statement.where(AuditLog.created_at < cutoff)
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    AuditLog.action.ilike(pattern),
                    AuditLog.actor_email.ilike(pattern),
                    AuditLog.target_type.ilike(pattern),
                    AuditLog.target_id.ilike(pattern),
                )
            )
        if action:
            statement = statement.where(AuditLog.action == action)
        if outcome:
            statement = statement.where(AuditLog.outcome == outcome)
        if actor_email:
            statement = statement.where(AuditLog.actor_email == actor_email)

        result = self.db.execute(statement)
        self.db.commit()
        return int(result.rowcount or 0)
