"""
Registration and login (BUILD SPEC section 6 - human control starts with
knowing who the human is). `register` creates a new tenant + its first
admin user in one step; everyone after that is invited via `invite` by an
admin and sets their password via `login`-style flow... kept intentionally
minimal here: `add_user` lets an existing admin create teammates directly
with a temporary password, since there's no email-sending identity yet to
build a real invite-link flow on top of (see the email module for why).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Tenant, User
from app.security.auth import hash_password, verify_password, create_access_token, get_current_user, require_role, AuthContext
from app.security.login_cooldown import (
    check_tenant_login_cooldown, record_tenant_login_failure, record_tenant_login_success,
    LoginCooldownActive,
)
from app.audit import logger as audit

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    company_name: str
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    user_id: str
    role: str


class AddUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "analyst"


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(400, "An account with this email already exists.")

    tenant = Tenant(name=body.company_name)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    user = User(
        tenant_id=tenant.id, email=body.email, role="admin",
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, tenant.id, user.role)
    return TokenResponse(access_token=token, tenant_id=tenant.id, user_id=user.id, role=user.role)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    try:
        check_tenant_login_cooldown(body.email)
    except LoginCooldownActive as e:
        raise HTTPException(429, str(e))

    user = db.query(User).filter_by(email=body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        record_tenant_login_failure(body.email)
        raise HTTPException(401, "Incorrect email or password.")

    record_tenant_login_success(body.email)
    token = create_access_token(user.id, user.tenant_id, user.role)
    return TokenResponse(access_token=token, tenant_id=user.tenant_id, user_id=user.id, role=user.role)


@router.post("/users", response_model=TokenResponse)
def add_user(body: AddUserRequest, db: Session = Depends(get_db),
             ctx: AuthContext = Depends(get_current_user)):
    if ctx.role != "admin":
        raise HTTPException(403, "Only an admin can add teammates.")
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(400, "An account with this email already exists.")

    user = User(
        tenant_id=ctx.tenant_id, email=body.email, role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.tenant_id, user.role)
    return TokenResponse(access_token=token, tenant_id=user.tenant_id, user_id=user.id, role=user.role)


@router.get("/me")
def me(ctx: AuthContext = Depends(get_current_user)):
    return {"user_id": ctx.user_id, "tenant_id": ctx.tenant_id, "role": ctx.role}


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    row_scope: dict

    class Config:
        from_attributes = True


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("admin"))):
    return db.query(User).filter_by(tenant_id=ctx.tenant_id).all()


class RowScopeUpdate(BaseModel):
    # e.g. {"region": ["South-East"]}. Empty dict = unrestricted.
    row_scope: dict[str, list[str]]


@router.patch("/users/{user_id}/row_scope", response_model=UserOut)
def update_row_scope(user_id: str, body: RowScopeUpdate, db: Session = Depends(get_db),
                      ctx: AuthContext = Depends(require_role("admin"))):
    user = db.query(User).filter_by(id=user_id, tenant_id=ctx.tenant_id).first()
    if not user:
        raise HTTPException(404, "User not found.")
    user.row_scope = body.row_scope
    db.commit()
    db.refresh(user)
    audit.log(db, ctx.tenant_id, "user_row_scope_updated", ctx.user_id,
               detail={"target_user_id": user_id, "row_scope": body.row_scope})
    return user
