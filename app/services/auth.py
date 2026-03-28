from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import User


VALID_ROLES = {"viewer", "operator", "admin"}


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def ensure_bootstrap_admin(self) -> None:
        existing = self.db.execute(select(User).where(User.email == self.settings.bootstrap_admin_email)).scalar_one_or_none()
        if existing:
            return
        self.db.add(
            User(
                email=self.settings.bootstrap_admin_email,
                full_name=self.settings.bootstrap_admin_name,
                password_hash=hash_password(self.settings.bootstrap_admin_password),
                role="admin",
                is_active=True,
            )
        )
        self.db.commit()

    def authenticate(self, email: str, password: str) -> User:
        user = self.db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user or not user.is_active or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
        return user

    @staticmethod
    def require_user(request: Request) -> int:
        user_id = request.session.get("user_id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
        return int(user_id)

    def get_current_user(self, request: Request) -> User:
        user_id = self.require_user(request)
        user = self.db.get(User, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session is invalid.")
        return user

    @staticmethod
    def require_role(user: User, allowed_roles: set[str]) -> None:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions.")

    @staticmethod
    def validate_role(role: str) -> str:
        if role not in VALID_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role.")
        return role
