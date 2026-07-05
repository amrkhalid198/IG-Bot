"""Dashboard HTML routes (Jinja2)."""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/")
async def index():
    return RedirectResponse("/dashboard")


@router.get("/dashboard")
async def campaigns_page(request: Request):
    return templates.TemplateResponse(request, "campaigns.html", {"page": "campaigns"})


@router.get("/dashboard/settings")
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"page": "settings"})
