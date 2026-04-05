"""
config/settings.py — production override.
Пути адаптированы под Docker-контейнер: модели монтируются в /app/models.
"""
import os
from pathlib import Path

BASE_DIR   = Path(__file__).parent.parent  # /app
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/app/models"))

# ── BM25 ─────────────────────────────────────────────────────────────────────
BM25_INDEX_PKL  = MODELS_DIR / "bm25_index.pkl"
BM25_K1         = 1.5
BM25_B          = 0.75
BM25_TOP_K      = 100
FINAL_TOP_N     = 20

# ── Артефакты ─────────────────────────────────────────────────────────────────
STE_LOOKUP_PKL         = MODELS_DIR / "ste_lookup.pkl"
USER_STE_FEATURES_PKL  = MODELS_DIR / "user_ste_features.parquet"
USER_CAT_FEATURES_PKL  = MODELS_DIR / "user_cat_features.pkl"
USER_CAT_PKL           = USER_CAT_FEATURES_PKL
SEASONAL_BOOST_PKL     = MODELS_DIR / "seasonal_boost.pkl"
LGBM_RANKER_PKL        = MODELS_DIR / "lgbm_ranker.pkl"
LGBM_MODEL_PKL         = LGBM_RANKER_PKL
QUERY_PREDICTOR_PKL    = MODELS_DIR / "query_predictor.pkl"
BUNDLE_RULES_PKL       = MODELS_DIR / "bundle_rules.pkl"
SYNONYMS_JSON          = MODELS_DIR / "synonyms.json"
SPELLCHECK_DICT        = MODELS_DIR / "spellcheck_dict.txt"
SPELLCHECK_DICT_PATH   = SPELLCHECK_DICT
PRICE_ANALOGUES_PKL    = MODELS_DIR / "price_analogues.pkl"
TRAIN_DATASET_PKL      = MODELS_DIR / "train_dataset.parquet"

# ── Спеллчекер ───────────────────────────────────────────────────────────────
SYMSPELL_MAX_EDIT = 2
SYMSPELL_PREFIX   = 7

# ── LightGBM LambdaRank ───────────────────────────────────────────────────────
LGBM_PARAMS = {
    "objective":         "lambdarank",
    "metric":            "ndcg",
    "ndcg_eval_at":      [10],
    "learning_rate":     0.05,
    "num_leaves":        63,
    "min_data_in_leaf":  10,
    "verbose":           -1,
    "n_jobs":            -1,
}
LGBM_NUM_ROUNDS     = 500
LGBM_EARLY_STOPPING = 50

# ── Признаки ─────────────────────────────────────────────────────────────────
FREQ_WINDOWS            = [30, 90, 365]
COLD_START_THRESHOLD    = 5
TAG_FREQ_MIN            = 3
TAG_FREQUENT_THRESHOLD  = TAG_FREQ_MIN
FEATURE_NAMES = [
    "bm25_score", "freq_30d", "freq_90d", "freq_365d",
    "days_since_last", "avg_spend", "cat_share",
    "season_boost", "is_repeat", "global_popularity",
]

# ── Query Predictor ───────────────────────────────────────────────────────────
QUERY_MIN_CHARS  = 3
QUERY_TOP_N      = 5
QUERY_AI_THRESH  = 0.65
SUGGEST_TOP_N    = QUERY_TOP_N

# ── Аналоги по цене ───────────────────────────────────────────────────────────
ANALOGUE_TOP_N       = 4
ANALOGUE_MIN_JACCARD = 0.25

# ── Bundle ────────────────────────────────────────────────────────────────────
BUNDLE_MIN_SUPPORT    = 0.01
BUNDLE_MIN_CONFIDENCE = 0.40
BUNDLE_MAX            = 3
BUNDLE_TOP_N          = 5

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST  = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT  = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB    = 0
PROFILE_TTL = 86_400
SESSION_TTL = 3_600

# ── API ───────────────────────────────────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000
