from datetime import datetime, timedelta
import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Invite, User
from app.services.auth import AuthService
from app.core.security import hash_password


class InviteService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_invite(self, email: str, full_name: str, role: str, invited_by: User, expires_in_days: int) -> Invite:
        role = AuthService.validate_role(role)
        invite = Invite(
            email=email,
            full_name=full_name,
            role=role,
            token=secrets.token_urlsafe(24),
            status="pending",
            invited_by_user_id=invited_by.id,
            expires_at=datetime.utcnow() + timedelta(days=max(expires_in_days, 1)),
        )
        self.db.add(invite)
        self.db.commit()
        self.db.refresh(invite)
        return invite

    def list_invites(self) -> list[Invite]:
        return self.db.execute(select(Invite).order_by(Invite.created_at.desc())).scalars().all()

    def get_by_token(self, token: str) -> Invite:
        invite = self.db.execute(select(Invite).where(Invite.token == token)).scalar_one_or_none()
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found.")
        return invite

    def accept_invite(self, token: str, password: str, full_name: str | None) -> User:
        invite = self.get_by_token(token)
        if invite.status != "pending" or invite.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Invite is no longer valid.")
        existing = self.db.execute(select(User).where(User.email == invite.email)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="A user with this email already exists.")
        user = User(
            email=invite.email,
            full_name=full_name or invite.full_name,
            password_hash=hash_password(password),
            role=invite.role,
            is_active=True,
        )
        invite.status = "accepted"
        invite.redeemed_at = datetime.utcnow()
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
