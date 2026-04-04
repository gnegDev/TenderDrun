import os

import models  # noqa: F401 — registers all tables with SQLModel metadata
from database import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routes import events, pages, search, ste, suggest

app = FastAPI(title="TenderDrun Search API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files from frontend/static/
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# API routes (prefixed so they don't clash with page routes)
app.include_router(search.router, prefix="/api")   # POST /api/search
app.include_router(events.router, prefix="/api")   # POST /api/event
app.include_router(ste.router)                     # GET  /ste/{ste_id}
app.include_router(suggest.router)                 # GET  /suggest, GET /explain

# HTML page routes — registered last to avoid shadowing API routes
app.include_router(pages.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
