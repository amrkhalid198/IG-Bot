"""FastAPI app entry point."""
import logging

from dotenv import load_dotenv

load_dotenv()  # must run before route modules read env vars

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from database import init_db  # noqa: E402
from routes import api, dashboard, webhook  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(title="IG Comment-to-DM Automation")

init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(webhook.router)
app.include_router(api.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
