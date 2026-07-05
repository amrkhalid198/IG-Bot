---
title: IG Bot
emoji: 💬
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
---

# IG Comment-to-DM Automation

A self-hosted, ManyChat-style tool. When someone comments a trigger keyword on one of your Instagram posts, the app automatically replies to their comment publicly **and** sends them a private DM — using only the **official Instagram Graph API**.

Built with FastAPI + SQLite. Dashboard at `/dashboard`. Deployable to Railway/Render via Docker.

---

## How it works

1. Facebook sends a webhook to `POST /webhook/instagram` whenever someone comments on your Instagram account's media.
2. The app validates the webhook signature (`X-Hub-Signature-256`), checks whether the comment is on a tracked post and contains a trigger keyword (case-insensitive, partial match).
3. On match, it posts a public reply under the comment and sends the commenter a DM via the **Private Replies API**.
4. Every processed comment ID is stored in the DB, so Facebook's webhook retries never cause double-firing.

**Why Private Replies matters:** a plain DM (`recipient: {id: user_id}`) only works if the user already has an open conversation with your business (the 24-hour messaging-window policy). The Private Replies API (`recipient: {comment_id: ...}`) is Instagram's official mechanism for messaging someone *because they commented* — it works with no prior conversation, within **7 days** of the comment. This app uses Private Replies first and falls back to a plain DM only if that fails.

---

## Instagram API Setup (start to finish)

You need: an Instagram account, a Facebook Page, and ~30 minutes.

### Step 1 — Convert Instagram to a Business or Creator account

1. Instagram app → your profile → **☰ → Settings and privacy → Account type and tools → Switch to professional account**.
2. Choose **Business** (or Creator — both work).
3. During setup (or later via **Edit profile → Page**), connect the account to a **Facebook Page**. If you don't have one, create one at [facebook.com/pages/create](https://www.facebook.com/pages/create). This link is mandatory — the Graph API reaches Instagram *through* the Page.

### Step 2 — Create a Facebook Developer App

1. Go to [developers.facebook.com](https://developers.facebook.com) → **My Apps → Create App**.
2. Use case: choose **Other**, then app type **Business**.
3. Name it (e.g. "My IG Automation") and create.
4. Note two values from **App settings → Basic**:
   - **App ID**
   - **App Secret** → this goes into `.env` as `FACEBOOK_APP_SECRET`.

### Step 3 — Add the Instagram product

1. In the App Dashboard, find **Add products** → add **Instagram** (Instagram API / Messenger API for Instagram, depending on how Meta currently labels it).
2. Also add **Webhooks** if it isn't added automatically.

### Step 4 — Permissions

The app needs these permissions on your access token:

| Permission | Used for |
|---|---|
| `instagram_basic` | Reading media/comments |
| `instagram_manage_comments` | Posting comment replies |
| `instagram_manage_messages` | Sending DMs / private replies |
| `pages_show_list` | Finding your Page |
| `pages_manage_metadata` | Webhook subscription on the Page |

While your app is in **Development Mode**, all of these work immediately — but **only for accounts with a role on the app** (you, plus anyone you add under **App roles → Roles**). That's enough to run this tool for your own Instagram account, no review needed.

To use it for accounts that don't have a role on the app, you must submit the permissions for **App Review** with a screencast of the dashboard + webhook flow (see "Messaging limitation" below).

### Step 5 — Generate a long-lived access token

1. Open the [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your app in the top-right dropdown.
3. Click **Generate Access Token** → log in → grant all permissions from Step 4. Make sure you select your Instagram account and its linked Page when prompted.
4. This gives you a **short-lived** token (~1 hour). Exchange it for a **long-lived** one (~60 days):

```
GET https://graph.facebook.com/v21.0/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={APP_ID}
  &client_secret={APP_SECRET}
  &fb_exchange_token={SHORT_LIVED_TOKEN}
```

(Paste that URL into a browser with the values filled in; the JSON response contains your long-lived `access_token`.)

5. Put it in `.env` as `INSTAGRAM_ACCESS_TOKEN` **and/or** paste it into the dashboard's Settings page.

#### Token refresh (every ~60 days)

Long-lived tokens expire after about 60 days. Before expiry, run the same `fb_exchange_token` call above using your **current long-lived token** as `fb_exchange_token` — you'll get a fresh 60-day token. Paste the new token into the Settings page. Set yourself a calendar reminder around day 50; there is no automatic renewal without implementing full OAuth.

### Step 6 — Find your IDs

With your token in the Graph API Explorer:

1. **Page ID:** `GET /me/accounts` → find your Page in the list → copy `id`.
2. **Instagram Business Account ID:** `GET /{page-id}?fields=instagram_business_account` → copy `instagram_business_account.id`.

Enter both in the dashboard Settings page (and the IG account ID in `.env` as `INSTAGRAM_BUSINESS_ACCOUNT_ID`).

### Step 7 — Configure the webhook

Your app must be deployed and reachable over **HTTPS** first (see Deployment below; for local testing use a tunnel like `ngrok http 8000`).

1. In `.env`, set `WEBHOOK_VERIFY_TOKEN` to any random string you invent (e.g. `openssl rand -hex 16`). Restart the app.
2. App Dashboard → **Webhooks** (or the Instagram product's webhook section) → choose object type **Instagram** → **Subscribe**.
3. Callback URL: `https://your-domain.com/webhook/instagram`
   Verify token: the exact string from `.env`.
4. Facebook sends a `GET` challenge; the app echoes it back automatically. If verification fails, check that the deployed app has the same `WEBHOOK_VERIFY_TOKEN`.
5. Subscribe to the **`comments`** field.
6. Additionally, subscribe your Page so events actually flow:
   `POST /{page-id}/subscribed_apps?subscribed_fields=feed` via the Graph API Explorer, or toggle it in the webhook UI if shown.

### Step 8 — Get a Post ID for a specific post/video

Campaigns track posts by their Graph API **media ID** (not the URL or shortcode):

1. In the Graph API Explorer: `GET /{ig-business-account-id}/media?fields=id,caption,media_type,permalink,timestamp&limit=25`
2. Find your post by caption/permalink in the response and copy its `id` (a long number like `17895695668004550`).
3. Paste it into the "Post ID" field when creating a campaign — the dashboard fetches a thumbnail preview so you can confirm it's the right post.

---

## ⚠️ Messaging limitation (read this)

- **Private Replies** (what this app uses) let you DM a commenter within **7 days** of their comment with **no prior conversation** — this is the intended, policy-compliant path for comment-to-DM automation.
- **Plain DMs** by user ID are restricted by the messaging-window policy: they fail unless the person has messaged your business and the conversation window is open. The app only uses this as a fallback.
- In **Development Mode**, everything works but only for app-role accounts. To automate DMs for the general public, submit `instagram_manage_messages` (with `instagram_basic`, `instagram_manage_comments`) for **App Review**: App Dashboard → **App Review → Permissions and features** → request Advanced Access → provide a screencast showing a comment triggering a reply + DM in this app, and a written use-case description. Review typically takes a few days to a few weeks.
- Respect Meta's automation policies: replies/DMs must be responses to user-initiated actions (a comment is one), not unsolicited bulk messaging.

---

## Running locally

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env          # then fill in your values
uvicorn main:app --reload
```

Open http://localhost:8000/dashboard — enter credentials in Settings, then create a campaign.

To receive webhooks locally: `ngrok http 8000`, then use the ngrok HTTPS URL in Step 7.

## Deployment (Railway)

1. Push this folder to a GitHub repo.
2. [railway.app](https://railway.app) → New Project → Deploy from GitHub repo. Railway detects the `Dockerfile` and `railway.toml` (health check on `/health`).
3. Add all variables from `.env.example` under **Variables**.
4. Note: SQLite data lives on the container filesystem and is lost on redeploys. Attach a Railway volume mounted where `app.db` lives, or provision Railway Postgres and set `DATABASE_URL` accordingly (SQLAlchemy handles both).
5. Use the generated `https://….up.railway.app` domain as your webhook callback URL.

(Render works the same way — create a Web Service from the repo with Docker; health check path `/health`.)

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Deployment health check |
| GET | `/webhook/instagram` | Facebook webhook verification |
| POST | `/webhook/instagram` | Comment events (signature-validated) |
| GET | `/dashboard` | Campaigns page |
| GET | `/dashboard/settings` | Credentials page |
| GET/POST | `/api/config` | Read (masked) / save credentials |
| GET/POST/PUT/PATCH/DELETE | `/api/campaigns…` | Campaign CRUD + toggle |
| GET | `/api/post-preview/{post_id}` | Fetch post thumbnail + caption |

## Security notes

- Webhook payloads are verified against `FACEBOOK_APP_SECRET` via `X-Hub-Signature-256` (HMAC-SHA256 over the raw body, constant-time compare). Unsigned/invalid requests are rejected with 403.
- The access token is never sent to the frontend — `/api/config` returns a masked version only.
- `.env` is gitignored. Never commit tokens.
- **The dashboard itself has no login.** Anyone with the URL can edit campaigns and overwrite credentials. Before going to production, put it behind auth (e.g. Railway's private networking, an OAuth proxy, or add HTTP Basic Auth to the dashboard/API routers).

## Project structure

```
├── main.py              # FastAPI app entry point
├── instagram.py         # Instagram Graph API client (retry/backoff, logging)
├── models.py            # SQLAlchemy models (Config, Campaign, ProcessedComment)
├── database.py          # DB session setup
├── routes/
│   ├── webhook.py       # Webhook verification + comment event processing
│   ├── dashboard.py     # Dashboard HTML routes
│   └── api.py           # REST API for campaigns/config
├── static/              # CSS + JS
├── templates/           # Jinja2 templates
├── .env.example
├── Dockerfile
├── railway.toml
└── requirements.txt
```
