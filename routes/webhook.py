"""Webhook endpoints for Instagram comment events."""
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from instagram import InstagramAPIError, InstagramClient
from models import Campaign, Config, ProcessedComment

logger = logging.getLogger("webhook")

router = APIRouter()

VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")


@router.get("/webhook/instagram")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge"),
):
    """Facebook webhook verification handshake."""
    if mode == "subscribe" and token and token == VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return Response(content=challenge or "", media_type="text/plain")
    logger.warning("Webhook verification failed (mode=%s)", mode)
    return Response(status_code=403)


def _valid_signature(payload: bytes, signature_header: str) -> bool:
    """Validate X-Hub-Signature-256 against the raw request body."""
    if not APP_SECRET:
        logger.error("FACEBOOK_APP_SECRET not set — rejecting webhook")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("Missing/malformed signature header: %r", signature_header)
        return False

    received = signature_header[len("sha256="):]
    expected = hmac.new(APP_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    match = hmac.compare_digest(expected, received)

    if not match:
        # Diagnostic: the algorithm is correct, so a mismatch means the secret
        # bytes differ from the secret Meta signed with (usually a wrong app
        # context). Logging prefixes + a secret fingerprint is safe (no secret
        # is revealed) and tells you empirically which side is wrong.
        secret_fp = hashlib.sha256(APP_SECRET.encode()).hexdigest()[:8]
        logger.warning(
            "Signature mismatch | body_len=%d | expected=sha256=%s… "
            "| received=%s… | app_secret_fp=%s | secret_len=%d",
            len(payload),
            expected[:12],
            received[:12],
            secret_fp,
            len(APP_SECRET),
        )
    return match


@router.post("/webhook/instagram")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()

    if not _valid_signature(raw_body, request.headers.get("X-Hub-Signature-256", "")):
        logger.warning("Invalid webhook signature — dropping event")
        return Response(status_code=403)

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=400)

    # Always ACK fast; Facebook retries non-200s aggressively.
    try:
        _process_payload(payload, db)
    except Exception:
        logger.exception("Error processing webhook payload")

    return {"status": "received"}


def _process_payload(payload: dict, db: Session):
    if payload.get("object") not in ("instagram", "page"):
        return

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            _handle_comment(change.get("value", {}), db)


def _handle_comment(value: dict, db: Session):
    comment_id = value.get("id")
    comment_text = (value.get("text") or "").lower()
    media = value.get("media") or {}
    post_id = media.get("id") or value.get("media_id")
    from_user = value.get("from") or {}
    commenter_id = from_user.get("id")

    if not comment_id or not post_id:
        logger.info("Comment event missing id/media id, skipping: %s", value)
        return

    config = db.query(Config).first()

    # Ignore our own replies to avoid loops
    if config and commenter_id and commenter_id == config.ig_business_account_id:
        return

    # Deduplication
    if db.query(ProcessedComment).filter_by(comment_id=comment_id).first():
        logger.info("Comment %s already processed, skipping", comment_id)
        return

    # Find a matching active campaign (tracked post + keyword match)
    campaigns = db.query(Campaign).filter_by(post_id=str(post_id), active=True).all()
    matched = None
    for campaign in campaigns:
        if any(kw in comment_text for kw in campaign.keyword_list()):
            matched = campaign
            break

    if not matched:
        logger.info("No campaign match for comment %s on post %s", comment_id, post_id)
        return

    token = (config.access_token if config else None) or os.getenv("INSTAGRAM_ACCESS_TOKEN")
    page_id = (config.page_id if config else None)
    if not token or not page_id:
        logger.error("Credentials not configured — cannot act on comment %s", comment_id)
        return

    # Mark processed BEFORE acting so webhook retries can't double-fire.
    db.add(ProcessedComment(comment_id=comment_id))
    db.commit()

    client = InstagramClient(token)

    try:
        client.reply_to_comment(comment_id, matched.comment_reply)
        logger.info("Replied to comment %s (campaign %s)", comment_id, matched.id)
    except InstagramAPIError as exc:
        logger.error("Failed to reply to comment %s: %s", comment_id, exc)

    # DM via Private Replies (works without prior conversation, 7-day window)
    try:
        client.send_private_reply(page_id, comment_id, matched.dm_message)
        logger.info("Sent private reply DM for comment %s (campaign %s)", comment_id, matched.id)
    except InstagramAPIError as exc:
        logger.error("Private reply failed for comment %s: %s", comment_id, exc)
        # Fallback: plain DM (only works if user has an open conversation)
        if commenter_id:
            try:
                client.send_dm(page_id, commenter_id, matched.dm_message)
                logger.info("Fallback DM sent to user %s", commenter_id)
            except InstagramAPIError as exc2:
                logger.error("Fallback DM also failed for user %s: %s", commenter_id, exc2)
