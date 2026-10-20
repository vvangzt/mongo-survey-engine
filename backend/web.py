"""Server-rendered pages for the survey application.

The UI is intentionally lightweight (Jinja2 + vanilla JavaScript) so it stays
easy to run and test without a Node.js build pipeline. Page authorization only
decides whether HTML can be rendered; every data operation is still guarded by
the JSON API.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pymongo.asynchronous.database import AsyncDatabase

from .dependencies import (
    DatabaseDep,
    OptionalCurrentUserIdDep,
)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

router = APIRouter(include_in_schema=False)


async def _page_user(
    db: AsyncDatabase, user_id
) -> dict | None:
    if user_id is None:
        return None
    user = await db["users"].find_one(
        {"_id": user_id, "status": "active"},
        {"username": 1, "email": 1, "display_name": 1},
    )
    if user is None:
        return None
    return {
        "id": str(user["_id"]),
        "username": user["username"],
        "display_name": user.get("display_name", user["username"]),
    }


def _login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(next_path, safe='/')}",
        status_code=303,
    )


def _safe_next(raw: str | None) -> str:
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return ""


def _ctx(
    request: Request,
    *,
    title: str,
    user: dict | None,
    **extra,
) -> dict:
    return {
        "request": request,
        "page_title": title,
        "current_user": user,
        **extra,
    }


async def _owned_survey(
    db: AsyncDatabase, user: dict, survey_id: str
) -> dict | None:
    try:
        oid = ObjectId(survey_id)
    except Exception:
        return None
    return await db["surveys"].find_one(
        {
            "_id": oid,
            "owner_id": ObjectId(user["id"]),
            "deleted_at": None,
        },
        {"_id": 1},
    )


def _not_found_page(request: Request, user: dict):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=404,
        context=_ctx(
            request,
            title="问卷不存在",
            user=user,
            error_title="问卷不存在",
            error_message="问卷可能已被删除，或者不属于当前账号。",
        ),
    )


@router.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
    next: str | None = None,
):
    user = await _page_user(db, user_id)
    if user is not None:
        return RedirectResponse(_safe_next(next) or "/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context=_ctx(
            request,
            title="登录",
            user=None,
            next_url=_safe_next(next),
        ),
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
    next: str | None = None,
):
    user = await _page_user(db, user_id)
    if user is not None:
        return RedirectResponse(_safe_next(next) or "/dashboard", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context=_ctx(
            request,
            title="注册",
            user=None,
            next_url=_safe_next(next),
        ),
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=_ctx(request, title="我的问卷", user=user),
    )


@router.get("/surveys/{survey_id}/edit", response_class=HTMLResponse)
async def editor_page(
    request: Request,
    survey_id: str,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    if await _owned_survey(db, user, survey_id) is None:
        return _not_found_page(request, user)
    return templates.TemplateResponse(
        request=request,
        name="editor.html",
        context=_ctx(
            request,
            title="编辑问卷",
            user=user,
            survey_id=survey_id,
        ),
    )


@router.get("/surveys/{survey_id}/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    survey_id: str,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    if await _owned_survey(db, user, survey_id) is None:
        return _not_found_page(request, user)
    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context=_ctx(
            request,
            title="问卷统计",
            user=user,
            survey_id=survey_id,
        ),
    )


@router.get("/survey/{slug}", response_class=HTMLResponse)
async def public_fill_page(
    request: Request,
    slug: str,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    return templates.TemplateResponse(
        request=request,
        name="fill.html",
        context=_ctx(
            request,
            title="填写问卷",
            user=user,
            slug=slug,
        ),
    )


__all__ = ["router"]
