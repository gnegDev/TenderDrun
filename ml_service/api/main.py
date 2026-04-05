"""
api/main.py — FastAPI ML backend
Запуск: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
  GET  /health              — статус всех компонентов
  GET  /suggest?q=&inn=     — AI-предсказание запроса в реальном времени (< 20 мс)
  GET  /search?q=&inn=      — поиск с ML-переранжированием (< 300 мс)
  POST /event               — логирование поведения (клик/bounce/dwell/purchase)
  GET  /profile/{inn}       — профиль заказчика
  GET  /bundles/{ste_id}    — «часто берут вместе»
  GET  /analogues/{ste_id} — аналоги с более низкой ценой (до 4 позиций)
  GET  /metrics             — дашборд для жюри (NDCG@10, latency, статус)
"""

import sys, time, json, pickle, logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

import pandas as pd
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import *

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# ── Глобальное состояние — загружается один раз при старте ────────────────────
class _S:
    engine          = None   # ml.search_index.SearchEngine
    reranker        = None   # ml.ranker.Reranker
    predictor       = None   # ml.search_index.QueryPredictor
    price_analogues = None   # ml.search_index.PriceAnalogueIndex
    user_cat: dict  = {}     # ИНН → {top_categories, category_share, total_contracts}
    ste_lookup: dict = {}    # ste_id → {name, category, specs_raw}
    redis           = None
    n_search    = 0
    n_suggest   = 0
    n_events    = 0
    latencies: list = []

S = _S()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== TenderHack ML API: запуск ===")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # Вспомогательная функция загрузки pkl
    def _pkl(path, label) -> Optional[object]:
        p = Path(path)
        if p.exists():
            with open(p, "rb") as f:
                d = pickle.load(f)
            log.info(f"✅ {label}")
            return d
        log.warning(f"⚠️  {label} не найден: {p}")
        return None

    # ── Артефакты ─────────────────────────────────────────────────────────────
    S.ste_lookup = _pkl(STE_LOOKUP_PKL,       "STE Lookup")     or {}
    S.user_cat   = _pkl(USER_CAT_PKL,         "User Cat")       or {}
    seasonal     = _pkl(SEASONAL_BOOST_PKL,   "Seasonal Boost") or {}
    global_pop   = _pkl(MODELS_DIR / "global_popularity.pkl", "Global Popularity") or {}

    user_ste_df: Optional[pd.DataFrame] = None
    if USER_STE_FEATURES_PKL.exists():
        user_ste_df = pd.read_parquet(USER_STE_FEATURES_PKL)
        log.info(f"✅ User STE Features: {len(user_ste_df):,} пар")
    else:
        log.warning(f"⚠️  user_ste_features.parquet не найден")

    # ── SearchEngine (BM25 + spell + synonyms) ────────────────────────────────
    from ml.search_index import SearchEngine
    S.engine = SearchEngine()
    S.engine.load_all()

    # ── Reranker (LightGBM + ExplainEngine + Bundle) ──────────────────────────
    from ml.ranker import FeatureExtractor, ExplainEngine, Reranker
    extractor  = FeatureExtractor(user_ste_df, S.user_cat, seasonal, global_pop)
    explainer  = ExplainEngine()
    S.reranker = Reranker(extractor, explainer)
    S.reranker.load_model(LGBM_MODEL_PKL)
    S.reranker.load_bundle(BUNDLE_RULES_PKL)

    # ── PriceAnalogueIndex ────────────────────────────────────────────────────
    from ml.search_index import PriceAnalogueIndex
    S.price_analogues = PriceAnalogueIndex()
    if PRICE_ANALOGUES_PKL.exists():
        S.price_analogues.load(PRICE_ANALOGUES_PKL)
        log.info("✅ PriceAnalogueIndex загружен")
    else:
        log.warning(f"⚠️  PriceAnalogueIndex не найден: {PRICE_ANALOGUES_PKL}")

    # ── QueryPredictor ────────────────────────────────────────────────────────
    from ml.search_index import QueryPredictor
    S.predictor = QueryPredictor()
    if QUERY_PREDICTOR_PKL.exists():
        S.predictor.load(QUERY_PREDICTOR_PKL)
        log.info("✅ QueryPredictor загружен")
    else:
        log.warning(f"⚠️  QueryPredictor не найден: {QUERY_PREDICTOR_PKL}")

    # ── Redis ─────────────────────────────────────────────────────────────────
    try:
        import redis
        S.redis = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
            decode_responses=True, socket_timeout=0.5,
        )
        S.redis.ping()
        log.info("✅ Redis подключён")
    except Exception as e:
        log.warning(f"⚠️  Redis недоступен ({e}) — сессии отключены")
        S.redis = None

    log.info("=== Сервер готов! ===")
    yield
    log.info("Сервер останавливается.")


app = FastAPI(title="TenderHack ML API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"],
)


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _get_session(inn: str) -> Optional[dict]:
    """Читает поведенческие сигналы сессии из Redis."""
    if not S.redis or not inn:
        return None
    try:
        raw = S.redis.get(f"sess:{inn}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _update_session(inn: str, ste_id: int, event: str, dwell_ms: int = 0):
    """
    Обновляет поведенческие сигналы в Redis.
    Сразу влияет на следующий запрос в сессии —
    это и есть «динамическая индексация» из требований ТЗ.

    click    → усиление СТЕ в следующей выдаче
    bounce   → ослабление (< 3 сек на карточке)
    dwell    → позитив при > 5 сек
    purchase → сильнейший позитивный сигнал
    """
    if not S.redis:
        return
    try:
        key = f"sess:{inn}"
        raw = S.redis.get(key)
        sig = json.loads(raw) if raw else {
            "clicks": {}, "bounces": {}, "dwells": {}, "added": {}
        }
        sid = str(ste_id)
        if event == "click":
            sig["clicks"][sid]  = sig["clicks"].get(sid, 0) + 1
        elif event == "bounce":
            sig["bounces"][sid]  = True
        elif event == "dwell":
            sig["dwells"][sid]   = max(sig["dwells"].get(sid, 0), dwell_ms)
        elif event == "purchase":
            sig["added"][sid]    = True
        S.redis.setex(key, SESSION_TTL, json.dumps(sig))
    except Exception as e:
        log.warning(f"Redis write: {e}")


def _get_session_queries(inn: str) -> list:
    """История запросов сессии — используется для буста в QueryPredictor."""
    if not S.redis or not inn:
        return []
    try:
        return S.redis.lrange(f"queries:{inn}", 0, 9) or []
    except Exception:
        return []


def _save_query(inn: str, q: str):
    if not S.redis or not inn or len(q.strip()) < 3:
        return
    try:
        k = f"queries:{inn}"
        S.redis.lpush(k, q.strip().lower())
        S.redis.ltrim(k, 0, 49)
        S.redis.expire(k, SESSION_TTL)
    except Exception:
        pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Healthcheck для Docker и жюри."""
    return {
        "status":    "ok",
        "bm25":      S.engine is not None and S.engine.bm25._bm25 is not None,
        "lgbm":      S.reranker is not None and S.reranker._ready,
        "predictor": S.predictor is not None and S.predictor._fitted,
        "bundle":    S.reranker is not None and bool(S.reranker._bundle),
        "redis":     S.redis is not None,
        "n_ste":     len(S.ste_lookup),
        "n_inn":     len(S.user_cat),
    }


@app.get("/suggest")
async def suggest(
    q:   str           = Query(..., min_length=1),
    inn: Optional[str] = Query(None),
):
    """
    AI-предсказание запроса в реальном времени.

    Вызывается при каждом нажатии клавиши (debounce 150 мс на клиенте).
    Топ-1 с is_ai_recommended=true показывается ВЫШЕ всех с плашкой «AI рекомендует».
    SLA: < 20 мс.

    Пример ответа:
    {
      "suggestions": [
        {"query": "перчатки медицинские", "score": 0.91,
         "is_ai_recommended": true, "source": "session"},
        {"query": "перчатки латексные",   "score": 0.60,
         "is_ai_recommended": false, "source": "popular"}
      ],
      "ai_recommended_query": "перчатки медицинские"
    }
    """
    S.n_suggest += 1

    if len(q.strip()) < QUERY_MIN_CHARS:
        return {"suggestions": [], "ai_recommended_query": None}

    sess_q = _get_session_queries(inn) if inn else []

    # Строим «горячий словарь» из названий СТЕ, кликнутых в этой сессии.
    # Токены этих названий буcтируют подсказки, содержащие те же слова.
    # O(clicks × tokens) ≈ O(50) — не влияет на латентность.
    session_vocab: set = set()
    if inn:
        session = _get_session(inn)
        if session:
            for ste_id_str in list(session.get("clicks", {}).keys())[:10]:
                info = S.ste_lookup.get(int(ste_id_str), {})
                name = info.get("name", "")
                if name and S.engine:
                    session_vocab.update(S.engine.prep.tokenize(name))
            # покупки весят больше — добавляем дважды чтобы слова дали больший охват
            for ste_id_str in list(session.get("added", {}).keys())[:5]:
                info = S.ste_lookup.get(int(ste_id_str), {})
                name = info.get("name", "")
                if name and S.engine:
                    session_vocab.update(S.engine.prep.tokenize(name))

    result = S.predictor.suggest(
        prefix          = q,
        user_inn        = inn,
        user_cat        = S.user_cat,
        session_queries = sess_q,
        session_vocab   = session_vocab,
        top_n           = QUERY_TOP_N,
    )

    _save_query(inn or "", q)
    return result


@app.get("/search")
async def search(
    q:     str           = Query(..., min_length=1),
    inn:   Optional[str] = Query(None),
    top_n: int           = Query(FINAL_TOP_N, ge=1, le=100),
):
    """
    Основной поиск с ML-переранжированием.

    Пайплайн:
      1. SpellCheck    — исправление опечатки (SymSpell, O(1))
      2. SynonymExpand — расширение запроса синонимами
      3. BM25          — топ-100 кандидатов
      4. LightGBM      — персонализированный топ-N
      5. ExplainEngine — why_tags для каждого результата
      6. Bundle        — «часто берут вместе» (inline)

    SLA: < 300 мс.
    """
    t0 = time.perf_counter()
    S.n_search += 1

    if S.engine is None:
        raise HTTPException(503, "Search Engine не загружен")

    # BM25 кандидаты (list[dict] с ключами ste_id, name, category, bm25_score)
    candidates, meta = S.engine.search(q, top_k=BM25_TOP_K)

    # ML переранжирование → list[dict] с ml_score, why_tags, bundle
    session = _get_session(inn) if inn else None
    results = S.reranker.rerank(
        user_inn   = inn or "anon",
        candidates = candidates,
        session    = session,
        top_n      = top_n,
    )

    # Добавляем ценовые аналоги к каждому результату — O(1) dict lookup
    if S.price_analogues:
        for r in results:
            r["price_analogues"] = S.price_analogues.get(r["ste_id"])

    _save_query(inn or "", q)

    lat = (time.perf_counter() - t0) * 1000
    S.latencies.append(lat)
    if len(S.latencies) > 1_000:
        S.latencies = S.latencies[-1_000:]

    return {
        "query":         q,
        "corrected":     meta.get("corrected"),
        "was_corrected": meta.get("was_corrected", False),
        "synonyms_used": meta.get("synonyms_added", []),
        "n_candidates":  len(candidates),
        "results":       results,
        "latency_ms":    round(lat, 1),
    }


class EventReq(BaseModel):
    user_inn:   str
    ste_id:     int
    event_type: str   # click | bounce | dwell | purchase
    dwell_ms:   int = 0


@app.post("/event")
async def log_event(req: EventReq):
    """
    Логирует поведение пользователя.
    Немедленно влияет на следующий запрос (динамическая индексация, требование ТЗ).
    """
    S.n_events += 1
    _update_session(req.user_inn, req.ste_id, req.event_type, req.dwell_ms)
    return {"status": "ok"}


@app.get("/profile/{inn}")
async def get_profile(inn: str):
    """Профиль заказчика: топ-категории, общая статистика."""
    p = S.user_cat.get(inn)
    if not p:
        raise HTTPException(404, f"ИНН {inn} не найден")
    return {
        "inn":             inn,
        "top_categories":  p.get("top_categories", []),
        "total_contracts": p.get("total_contracts", 0),
    }


@app.get("/bundles/{ste_id}")
async def get_bundles(ste_id: int, top_n: int = 3):
    """«Часто берут вместе» для конкретной СТЕ."""
    if not S.reranker or not S.reranker._bundle:
        raise HTTPException(503, "Bundle не загружен")
    bundles = S.reranker._bundle.get(ste_id, [])[:top_n]
    # Обогащаем названиями из ste_lookup если имя пустое
    for b in bundles:
        if not b.get("name"):
            b["name"] = S.ste_lookup.get(b["ste_id"], {}).get("name", "")
    return {"ste_id": ste_id, "bundles": bundles}


@app.get("/analogues/{ste_id}")
async def get_analogues(ste_id: int):
    """
    Аналоги с более низкой ценой для конкретной СТЕ.

    Используется на карточке товара («Дешевле на X%»).
    Возвращает до ANALOGUE_TOP_N позиций из той же категории
    с Jaccard-сходством названий ≥ ANALOGUE_MIN_JACCARD.

    Пример ответа:
    {
      "ste_id": 12345,
      "current_price": 1500.0,
      "analogues": [
        {"ste_id": 23456, "name": "...", "median_price": 1100.0, "savings_pct": 26.7},
        ...
      ]
    }
    """
    if S.price_analogues is None or not S.price_analogues._index:
        raise HTTPException(503, "PriceAnalogueIndex не загружен — запустите 02_build_index.py")
    analogues = S.price_analogues.get(ste_id)
    current_price = S.ste_lookup.get(ste_id, {}).get("median_price")
    return {
        "ste_id":        ste_id,
        "current_price": current_price,
        "analogues":     analogues,
    }


@app.get("/metrics")
async def get_metrics():
    """
    Дашборд метрик для жюри.
    Показывает: latency (p50/p95), статус компонентов, NDCG@10 из обучения.
    """
    lats = sorted(S.latencies)
    p50  = lats[len(lats) // 2]        if lats else 0.0
    p95  = lats[int(len(lats) * 0.95)] if lats else 0.0

    # Результаты оценки из обучения (сохраняются ml/ranker.py)
    eval_data = {}
    eval_path = MODELS_DIR / "eval_results.json"
    if eval_path.exists():
        with open(eval_path) as f:
            eval_data = json.load(f)

    return {
        "requests": {
            "search":  S.n_search,
            "suggest": S.n_suggest,
            "events":  S.n_events,
        },
        "latency": {
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "target": "< 300 мс",
        },
        "components": {
            "bm25":      S.engine is not None and S.engine.bm25._bm25 is not None,
            "lgbm":      S.reranker is not None and S.reranker._ready,
            "predictor": S.predictor is not None and S.predictor._fitted,
            "bundle":    S.reranker is not None and bool(S.reranker._bundle),
            "redis":     S.redis is not None,
        },
        "data": {
            "n_ste":      len(S.ste_lookup),
            "n_profiles": len(S.user_cat),
        },
        "eval": eval_data,   # bm25_ndcg10, lgbm_ndcg10, lift_pct, mrr
    }
