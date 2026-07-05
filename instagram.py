"""Instagram Graph API client.

Only official Graph API endpoints are used. All calls are logged and
retried with exponential backoff on rate limits / transient errors.

Key design note: for comment-to-DM automation, Instagram provides the
*Private Replies* API — you message the author of a comment by passing
{"comment_id": ...} as the recipient. This works even if the user has
never messaged your business first (allowed within 7 days of the
comment) and is the mechanism tools like ManyChat use. A plain
user-id DM (send_dm) is also provided, but it is subject to the
24-hour messaging-window policy and will fail for users who never
messaged you.
"""
import logging
import time

import requests

logger = logging.getLogger("instagram")

GRAPH_URL = "https://graph.facebook.com/v21.0"

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2

# Graph API error codes that indicate rate limiting / transient issues
RATE_LIMIT_CODES = {4, 17, 32, 613, 80007}
TRANSIENT_CODES = {1, 2}  # unknown / service temporarily unavailable


class InstagramAPIError(Exception):
    def __init__(self, message, status_code=None, error_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response = response


class InstagramClient:
    def __init__(self, access_token: str):
        if not access_token:
            raise ValueError("access_token is required")
        self.access_token = access_token

    # ------------------------------------------------------------------
    # Low-level request with logging + retry/backoff
    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, *, params=None, data=None):
        url = f"{GRAPH_URL}/{path.lstrip('/')}"
        params = dict(params or {})
        params["access_token"] = self.access_token

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.request(method, url, params=params, data=data, timeout=30)
            except requests.RequestException as exc:
                last_error = InstagramAPIError(f"Network error: {exc}")
                logger.warning("Graph API network error (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)
                time.sleep(BACKOFF_BASE_SECONDS ** attempt)
                continue

            # Never log the token
            logger.info("Graph API %s /%s -> %d: %s", method, path, resp.status_code, resp.text[:500])

            if resp.ok:
                return resp.json() if resp.text else {}

            try:
                error = resp.json().get("error", {})
            except ValueError:
                error = {}
            code = error.get("code")
            message = error.get("message", resp.text[:300])

            if code in RATE_LIMIT_CODES or code in TRANSIENT_CODES or resp.status_code >= 500:
                wait = BACKOFF_BASE_SECONDS ** attempt
                logger.warning(
                    "Graph API rate-limited/transient error (code=%s), retrying in %ss (attempt %d/%d)",
                    code, wait, attempt, MAX_RETRIES,
                )
                last_error = InstagramAPIError(message, resp.status_code, code, error)
                time.sleep(wait)
                continue

            # Non-retryable (bad token, missing permission, invalid ID, etc.)
            raise InstagramAPIError(message, resp.status_code, code, error)

        raise last_error or InstagramAPIError("Graph API request failed after retries")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reply_to_comment(self, comment_id: str, message: str) -> dict:
        """Post a public reply under a comment.

        POST /{comment_id}/replies
        Requires: instagram_manage_comments
        """
        return self._request("POST", f"{comment_id}/replies", data={"message": message})

    def send_private_reply(self, page_id: str, comment_id: str, message: str) -> dict:
        """Send a private DM to the author of a comment (Private Replies API).

        POST /{page_id}/messages with recipient={"comment_id": ...}
        Requires: instagram_manage_messages
        Works within 7 days of the comment, even if the user never DMed you.
        This is the primary comment-to-DM mechanism.
        """
        import json

        return self._request(
            "POST",
            f"{page_id}/messages",
            data={
                "recipient": json.dumps({"comment_id": comment_id}),
                "message": json.dumps({"text": message}),
            },
        )

    def send_dm(self, page_id: str, instagram_user_id: str, message: str) -> dict:
        """Send a plain DM by IG-scoped user ID.

        Subject to the messaging-window policy: fails unless the user has
        an open conversation with your business. Used as a fallback only.
        """
        import json

        return self._request(
            "POST",
            f"{page_id}/messages",
            data={
                "recipient": json.dumps({"id": instagram_user_id}),
                "message": json.dumps({"text": message}),
            },
        )

    def get_post_details(self, post_id: str) -> dict:
        """Fetch media details for dashboard preview."""
        fields = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
        data = self._request("GET", post_id, params={"fields": fields})
        # Videos expose thumbnail_url; images expose media_url.
        thumbnail = data.get("thumbnail_url") or data.get("media_url")
        return {
            "id": data.get("id"),
            "caption": data.get("caption", ""),
            "media_type": data.get("media_type"),
            "thumbnail_url": thumbnail,
            "permalink": data.get("permalink"),
            "timestamp": data.get("timestamp"),
        }

    def refresh_long_lived_token(self, app_id: str, app_secret: str) -> dict:
        """Exchange the current token for a fresh 60-day long-lived token."""
        return self._request(
            "GET",
            "oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": self.access_token,
            },
        )
