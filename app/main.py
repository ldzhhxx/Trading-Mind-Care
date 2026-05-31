"""FastAPI application entry point."""
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import init_db
from app.scheduler import start_scheduler, daily_decay
from app.feishu import send_daily_notification
from app.routes import plans, reviews, vulnerabilities, settings, notifications, stats, daily_report, data, calendar, weekly, rules, insights, journal, monthly


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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    errors = exc.errors()
    msg = "; ".join(e.get("msg", "验证错误") for e in errors)
    return JSONResponse(status_code=422, content={"detail": msg})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})

# Routes
app.include_router(plans.router)
app.include_router(reviews.router)
app.include_router(vulnerabilities.router)
app.include_router(settings.router)
app.include_router(notifications.router)
app.include_router(stats.router)
app.include_router(daily_report.router)
app.include_router(data.router)
app.include_router(calendar.router)
app.include_router(weekly.router)
app.include_router(rules.router)
app.include_router(insights.router)
app.include_router(journal.router)
app.include_router(monthly.router)

# Static files
static_dir = get_static_dir()
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))
