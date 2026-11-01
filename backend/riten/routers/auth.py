from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import db, security
from ..config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: LoginBody, response: Response):
    row = db.fetch_one("SELECT user_id, username, role, password_hash FROM app_user WHERE username = %s AND is_active", (body.username,))
    if not security.verify_password(row["password_hash"] if row else None, body.password):
        raise HTTPException(401, "Incorrect username or password.")
    s = get_settings()
    response.set_cookie(security.COOKIE_NAME, security.issue_token(row["user_id"]), httponly=True, samesite="strict",
                        secure=s.cookie_secure, max_age=s.jwt_ttl_minutes * 60, path="/")
    return {"user_id": row["user_id"], "username": row["username"], "role": row["role"]}


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(security.COOKIE_NAME, path="/")


@router.get("/me")
def me(user: dict = Depends(security.current_user)):
    return user
