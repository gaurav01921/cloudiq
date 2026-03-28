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
