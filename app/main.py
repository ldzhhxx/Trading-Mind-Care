"""FastAPI application entry point."""
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from app.database import init_db
from app.scheduler import start_scheduler, daily_decay
from app.feishu import send_daily_notification
from app.routes import plans, reviews, vulnerabilities, settings, notifications, stats, daily_report


def get_static_dir() -> str:
    """Get static files directory, compatible with PyInstaller."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Run startup checks
    await daily_decay()
    await send_daily_notification()
    start_scheduler()
    yield


app = FastAPI(title="Trading Mind Care", lifespan=lifespan)

# Routes
app.include_router(plans.router)
app.include_router(reviews.router)
app.include_router(vulnerabilities.router)
app.include_router(settings.router)
app.include_router(notifications.router)
app.include_router(stats.router)
app.include_router(daily_report.router)

# Static files
static_dir = get_static_dir()
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
