"""REST API for campaigns and config (consumed by the dashboard JS)."""
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from instagram import InstagramAPIError, InstagramClient
from models import Campaign, Config

logger = logging.getLogger("api")

router = APIRouter(prefix="/api")


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
class ConfigIn(BaseModel):
    access_token: str = ""
    page_id: str = ""
    ig_business_account_id: str = ""


class CampaignIn(BaseModel):
    # populate_by_name lets callers use either the canonical field name or an
    # alias. Aliases mean older/manual payloads never 422 on naming again.
    model_config = ConfigDict(populate_by_name=True)

    name: str = "Untitled campaign"
    post_id: str
    keywords: str = Field(
        validation_alias=AliasChoices(
            "keywords", "trigger_keywords", "trigger_words", "keyword",
        ),
    )
    comment_reply: str = Field(
        validation_alias=AliasChoices("comment_reply", "public_reply", "reply"),
    )
    dm_message: str = Field(
        validation_alias=AliasChoices("dm_message", "dm", "message"),
    )
    active: bool = True

    @field_validator("keywords", mode="before")
    @classmethod
    def _coerce_keywords(cls, v):
        """Accept a list of keywords and store as a comma-separated string."""
        if isinstance(v, (list, tuple)):
            return ", ".join(str(x).strip() for x in v if str(x).strip())
        return v


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
def _mask(token: str) -> str:
    if not token:
        return ""
    return token[:6] + "…" + token[-4:] if len(token) > 12 else "•••"


@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config:
        return {"access_token_masked": "", "page_id": "", "ig_business_account_id": "", "configured": False}
    return {
        # Never send the raw token back to the frontend.
        "access_token_masked": _mask(config.access_token or ""),
        "page_id": config.page_id or "",
        "ig_business_account_id": config.ig_business_account_id or "",
        "configured": bool(config.access_token and config.page_id),
    }


@router.post("/config")
def save_config(data: ConfigIn, db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config:
        config = Config(id=1)
        db.add(config)
    if data.access_token:  # empty means "keep existing"
        config.access_token = data.access_token
    config.page_id = data.page_id
    config.ig_business_account_id = data.ig_business_account_id
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------
# Post preview
# ----------------------------------------------------------------------
@router.get("/post-preview/{post_id}")
def post_preview(post_id: str, db: Session = Depends(get_db)):
    config = db.query(Config).first()
    token = (config.access_token if config else None) or os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not token:
        raise HTTPException(400, "Instagram credentials not configured yet (Settings page)")
    try:
        return InstagramClient(token).get_post_details(post_id)
    except InstagramAPIError as exc:
        raise HTTPException(422, f"Could not fetch post: {exc}")


# ----------------------------------------------------------------------
# Campaigns CRUD
# ----------------------------------------------------------------------
@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    return [c.to_dict() for c in db.query(Campaign).order_by(Campaign.created_at.desc()).all()]


@router.post("/campaigns")
def create_campaign(
    data: CampaignIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Save to SQLite FIRST — no network call is in the save path, so the
    # request can never hang/timeout on a slow Instagram Graph API response.
    campaign = Campaign(**data.model_dump())
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    # Fetch the thumbnail/caption AFTER the response is sent, in the background.
    background_tasks.add_task(_cache_preview_bg, campaign.id, campaign.post_id)
    return campaign.to_dict()


@router.put("/campaigns/{campaign_id}")
def update_campaign(
    campaign_id: int,
    data: CampaignIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    old_post_id = campaign.post_id
    for field, value in data.model_dump().items():
        setattr(campaign, field, value)
    db.commit()
    # Refresh the cached preview in the background only if the post changed.
    if campaign.post_id != old_post_id:
        background_tasks.add_task(_cache_preview_bg, campaign.id, campaign.post_id)
    return campaign.to_dict()


@router.patch("/campaigns/{campaign_id}/toggle")
def toggle_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    campaign.active = not campaign.active
    db.commit()
    return campaign.to_dict()


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    db.delete(campaign)
    db.commit()
    return {"ok": True}


def _cache_preview_bg(campaign_id: int, post_id: str):
    """Background task: cache post caption/thumbnail after the response is sent.

    Runs AFTER the campaign is already committed, on its own DB session, so a
    slow or failing Instagram call can never delay or block the save. Any
    error here is logged and swallowed — the campaign still exists either way.
    """
    db = SessionLocal()
    try:
        config = db.query(Config).first()
        token = (config.access_token if config else None) or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        if not token:
            return
        details = InstagramClient(token).get_post_details(post_id)
        campaign = db.get(Campaign, campaign_id)
        if campaign:
            campaign.post_caption = (details.get("caption") or "")[:300]
            campaign.post_thumbnail = details.get("thumbnail_url")
            db.commit()
    except Exception as exc:  # never let a background failure surface
        logger.warning("Could not cache preview for post %s: %s", post_id, exc)
    finally:
        db.close()
