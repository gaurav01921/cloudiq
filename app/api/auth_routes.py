from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Invite, User
from app.schemas.admin import AuditLogResponse, InviteAcceptRequest, InviteCreateRequest, InviteResponse
from app.schemas.auth import LoginRequest, UserCreateRequest, UserResponse, UserUpdateRequest
from app.services.audit import AuditService
from app.services.auth import AuthService
from app.core.security import hash_password
from app.services.invite import InviteService

router = APIRouter(prefix="/auth", tags=["auth"])
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    return AuthService(db).get_current_user(request)


def require_operator(user: User = Depends(current_user)) -> User:
    AuthService.require_role(user, {"operator", "admin"})
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    AuthService.require_role(user, {"admin"})
    return user


@router.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> UserResponse:
    user = AuthService(db).authenticate(payload.email, payload.password)
    request.session["user_id"] = user.id
    AuditService(db).record(action="auth.login", actor=user, target_type="user", target_id=str(user.id))
    return UserResponse.model_validate(user)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    actor = None
    user_id = request.session.get("user_id")
    if user_id:
        actor = db.get(User, int(user_id))
    if actor:
        AuditService(db).record(action="auth.logout", actor=actor, target_type="user", target_id=str(actor.id))
    request.session.clear()
    return {"status": "logged_out"}


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("/users", response_model=list[UserResponse])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[UserResponse]:
    rows = db.execute(select(User).order_by(User.created_at.asc())).scalars().all()
    return [UserResponse.model_validate(row) for row in rows]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    role = AuthService.validate_role(payload.role)
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    AuditService(db).record(
        action="user.create",
        actor=admin,
        target_type="user",
        target_id=str(user.id),
        details={"email": user.email, "role": user.role},
    )
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = db.get(User, user_id)
    if not user:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="User not found.")
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        user.role = AuthService.validate_role(payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    AuditService(db).record(
        action="user.update",
        actor=admin,
        target_type="user",
        target_id=str(user.id),
        details={
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active,
        },
    )
    return UserResponse.model_validate(user)


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[AuditLogResponse]:
    from app.models import AuditLog

    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)).scalars().all()
    return [AuditLogResponse.model_validate(row) for row in rows]


@router.get("/invites", response_model=list[InviteResponse])
def list_invites(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[InviteResponse]:
    invites = InviteService(db).list_invites()
    return [
        InviteResponse(
            id=invite.id,
            email=invite.email,
            full_name=invite.full_name,
            role=invite.role,
            status=invite.status,
            invited_by_user_id=invite.invited_by_user_id,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            redeemed_at=invite.redeemed_at,
            invite_link=f"/auth/accept-invite?token={invite.token}",
        )
        for invite in invites
    ]


@router.post("/invites", response_model=InviteResponse, status_code=status.HTTP_201_CREATED)
def create_invite(
    payload: InviteCreateRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> InviteResponse:
    invite = InviteService(db).create_invite(
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        invited_by=admin,
        expires_in_days=payload.expires_in_days,
    )
    AuditService(db).record(
        action="invite.create",
        actor=admin,
        target_type="invite",
        target_id=str(invite.id),
        details={"email": invite.email, "role": invite.role},
    )
    return InviteResponse(
        id=invite.id,
        email=invite.email,
        full_name=invite.full_name,
        role=invite.role,
        status=invite.status,
        invited_by_user_id=invite.invited_by_user_id,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        redeemed_at=invite.redeemed_at,
        invite_link=f"/auth/accept-invite?token={invite.token}",
    )


@router.get("/accept-invite", include_in_schema=False)
def accept_invite_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "accept-invite.html")


@router.post("/accept-invite", response_model=UserResponse)
def accept_invite(
    token: str,
    payload: InviteAcceptRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> UserResponse:
    user = InviteService(db).accept_invite(token=token, password=payload.password, full_name=payload.full_name)
    request.session["user_id"] = user.id
    AuditService(db).record(
        action="invite.accept",
        actor=user,
        target_type="user",
        target_id=str(user.id),
        details={"email": user.email},
    )
    return UserResponse.model_validate(user)
