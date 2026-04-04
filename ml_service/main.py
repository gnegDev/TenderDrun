"""
Заглушка ML-сервиса.
Заменить реальной реализацией при наличии модели.
"""
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ML Service (stub)")


class Candidate(BaseModel):
    ste_id: str
    name: str
    category: str | None = None
    bm25_score: float = 1.0


class RankRequest(BaseModel):
    query: str
    inn: str
    candidates: list[Candidate]
    history: list[dict] = []


class EventRequest(BaseModel):
    inn: str
    ste_id: str
    event_type: str
    dwell_ms: int | None = None


@app.post("/rank")
def rank(body: RankRequest):
    results = [
        {"ste_id": c.ste_id, "score": 1.0, "reason": "stub"}
        for c in body.candidates
    ]
    return {"results": results, "suggested_query": None}


@app.post("/event")
def event(body: EventRequest):
    return {"status": "ok"}


@app.get("/suggest")
def suggest(inn: str):
    return {"suggested_query": None}


@app.get("/health")
def health():
    return {"status": "ok"}
