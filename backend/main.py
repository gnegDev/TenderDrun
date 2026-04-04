import models  # noqa: F401 — registers all tables with SQLModel metadata
from database import init_db
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import events, search, ste, suggest

app = FastAPI(title="TenderDrun Search API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(events.router)
app.include_router(ste.router)
app.include_router(suggest.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
