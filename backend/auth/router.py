"""Authentication endpoints and cookie handling."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pymongo.asynchronous.database import AsyncDatabase

from ..config import get_settings
from ..dependencies import CurrentUserIdDep, get_db
from .schemas import LoginIn, RegisterIn, TokenOut, UserOut
from .security import create_access_token
from .service import (
    AccountDisabledError,
    AuthService,
    EmailTakenError,
    InvalidCredentialsError,
    UsernameTakenError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def get_auth_service(db: Annotated[AsyncDatabase, Depends(get_db)]) -> AuthService:
    return AuthService(db)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _set_auth_cookie(response: Response, token: str, expires_in: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.access_token_cookie,
        value=token,
        max_age=expires_in,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post(
    "/register",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册账号并自动登录",
)
async def register(
    payload: RegisterIn,
    response: Response,
    service: AuthServiceDep,
) -> TokenOut:
    try:
        user = await service.register(payload)
    except UsernameTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except EmailTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    token, expires_in = create_access_token(user["_id"])
    _set_auth_cookie(response, token, expires_in)
    return TokenOut(access_token=token, user=UserOut.from_document(user))


@router.post(
    "/login",
    response_model=TokenOut,
    summary="用户名密码登录",
)
async def login(
    payload: LoginIn,
    response: Response,
    service: AuthServiceDep,
) -> TokenOut:
    try:
        user = await service.authenticate(payload.username, payload.password)
    except (InvalidCredentialsError, AccountDisabledError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        ) from exc

    token, expires_in = create_access_token(user["_id"])
    _set_auth_cookie(response, token, expires_in)
    return TokenOut(access_token=token, user=UserOut.from_document(user))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="退出登录",
)
async def logout(response: Response) -> Response:
    settings = get_settings()
    response.delete_cookie(
        key=settings.access_token_cookie,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/me",
    response_model=UserOut,
    summary="获取当前登录用户",
)
async def me(
    user_id: CurrentUserIdDep,
    service: AuthServiceDep,
) -> UserOut:
    user = await service.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="account is unavailable",
        )
    return UserOut.from_document(user)


__all__ = ["router"]
