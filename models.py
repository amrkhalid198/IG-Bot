"""SQLAlchemy models."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Config(Base):
    """Single-row table storing Instagram/Facebook credentials.

    Note: the access token lives in the DB so it can be updated from the
    dashboard without redeploying. INSTAGRAM_ACCESS_TOKEN in .env is used
    as a fallback/initial value.
    """

    __tablename__ = "config"

    id = Column(Integer, primary_key=True, default=1)
    access_token = Column(Text, nullable=True)
    page_id = Column(String(64), nullable=True)
    ig_business_account_id = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False, default="Untitled campaign")
    post_id = Column(String(64), nullable=False, index=True)
    post_caption = Column(Text, nullable=True)      # cached preview
    post_thumbnail = Column(Text, nullable=True)    # cached preview
    keywords = Column(Text, nullable=False)         # comma-separated
    comment_reply = Column(Text, nullable=False)
    dm_message = Column(Text, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def keyword_list(self):
        return [k.strip().lower() for k in (self.keywords or "").split(",") if k.strip()]

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "post_id": self.post_id,
            "post_caption": self.post_caption,
            "post_thumbnail": self.post_thumbnail,
            "keywords": self.keywords,
            "comment_reply": self.comment_reply,
            "dm_message": self.dm_message,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProcessedComment(Base):
    __tablename__ = "processed_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comment_id = Column(String(64), nullable=False, unique=True, index=True)
    processed_at = Column(DateTime(timezone=True), default=utcnow)
