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
from .questions.service import QuestionLibraryService

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
    return _error_page(
        request,
        user,
        title="问卷不存在",
        message="问卷可能已被删除，或者不属于当前账号。",
    )


def _error_page(
    request: Request,
    user: dict,
    *,
    title: str,
    message: str,
    status_code: int = 404,
):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=status_code,
        context=_ctx(
            request,
            title=title,
            user=user,
            error_title=title,
            error_message=message,
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


# ---------------------------------------------------------------------------
# phase 2: shared question library pages
# ---------------------------------------------------------------------------


def _object_id_or_none(raw: str):
    try:
        return ObjectId(raw)
    except Exception:
        return None


async def _question_visible(
    db: AsyncDatabase, user: dict, question_id: str
) -> bool:
    service = QuestionLibraryService(db)
    oid = _object_id_or_none(question_id)
    if oid is None:
        return False
    try:
        await service.get_question(ObjectId(user["id"]), oid)
    except Exception:
        return False
    return True


async def _library_visible(
    db: AsyncDatabase, user: dict, library_id: str
) -> bool:
    service = QuestionLibraryService(db)
    oid = _object_id_or_none(library_id)
    if oid is None:
        return False
    try:
        await service.get_library(ObjectId(user["id"]), oid)
    except Exception:
        return False
    return True


@router.get("/questions", response_class=HTMLResponse)
async def questions_page(
    request: Request,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    return templates.TemplateResponse(
        request=request,
        name="questions.html",
        context=_ctx(request, title="题目库", user=user),
    )


@router.get("/questions/{question_id}", response_class=HTMLResponse)
async def question_detail_page(
    request: Request,
    question_id: str,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    if not await _question_visible(db, user, question_id):
        return _error_page(
            request,
            user,
            title="题目不存在",
            message="题目可能已被删除，或者没有共享给你。",
        )
    return templates.TemplateResponse(
        request=request,
        name="question_detail.html",
        context=_ctx(
            request, title="题目详情", user=user, question_id=question_id
        ),
    )


@router.get("/questions/{question_id}/stats", response_class=HTMLResponse)
async def question_stats_page(
    request: Request,
    question_id: str,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    if not await _question_visible(db, user, question_id):
        return _error_page(
            request,
            user,
            title="题目不存在",
            message="题目可能已被删除，或者没有共享给你。",
        )
    return templates.TemplateResponse(
        request=request,
        name="question_stats.html",
        context=_ctx(
            request, title="跨问卷统计", user=user, question_id=question_id
        ),
    )


@router.get("/libraries", response_class=HTMLResponse)
async def libraries_page(
    request: Request,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    return templates.TemplateResponse(
        request=request,
        name="libraries.html",
        context=_ctx(request, title="题库", user=user),
    )


@router.get("/libraries/{library_id}", response_class=HTMLResponse)
async def library_detail_page(
    request: Request,
    library_id: str,
    user_id: OptionalCurrentUserIdDep,
    db: DatabaseDep,
):
    user = await _page_user(db, user_id)
    if user is None:
        return _login_redirect(request)
    if not await _library_visible(db, user, library_id):
        return _error_page(
            request,
            user,
            title="题库不存在",
            message="题库可能已被删除，或者不是公开题库。",
        )
    return templates.TemplateResponse(
        request=request,
        name="library_detail.html",
        context=_ctx(
            request, title="题库详情", user=user, library_id=library_id
        ),
    )


__all__ = ["router"]
