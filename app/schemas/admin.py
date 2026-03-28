from datetime import datetime

from pydantic import BaseModel, EmailStr


class AuditLogResponse(BaseModel):
    id: int
    actor_user_id: int | None
    actor_email: EmailStr | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    details_json: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class InviteCreateRequest(BaseModel):
    email: EmailStr
    full_name: str
    role: str
    expires_in_days: int = 7


class InviteAcceptRequest(BaseModel):
    full_name: str | None = None
    password: str


class InviteResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    status: str
    invited_by_user_id: int
    created_at: datetime
    expires_at: datetime
    redeemed_at: datetime | None
    invite_link: str

