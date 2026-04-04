"""
Заглушка ML-сервиса. Возвращает пустые ответы.
Заменить реальной реализацией при наличии модели.
"""
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="ML Service (stub)")


class RankRequest(BaseModel):
    query: str
    inn: str
    history: dict


class ReindexRequest(BaseModel):
    inn: str


@app.post("/rank")
def rank(body: RankRequest):
    return {"results": [], "suggested_query": None}


@app.post("/reindex")
def reindex(body: ReindexRequest):
    return {"status": "ok"}


@app.get("/suggest")
def suggest(inn: str):
    return {"suggested_query": None}


@app.get("/health")
def health():
    return {"status": "ok"}
