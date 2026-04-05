"""
ml/ranker.py
============
Скрипт 3 из 3. Запускается после ml.pipeline и ml.search_index.

Что делает:
  1. Обучает LightGBM LambdaRank на train_dataset.parquet
  2. Валидирует на holdout-ИНН (не пересекается с train)
  3. Печатает NDCG@10 / MRR до и после ML (BM25 baseline vs LightGBM)
  4. Сохраняет lgbm_ranker.pkl

В runtime (через API):
  - Reranker.rerank()  — переранжирует кандидатов от BM25
  - ExplainEngine.tags() — генерирует why_tags для UI

Запуск обучения:
    python -m ml.ranker

Запуск только оценки (если модель уже обучена):
    python -m ml.ranker --eval
"""

import sys, pickle, logging, argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import *

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE EXTRACTOR
# ─────────────────────────────────────────────────────────────────────────────

class FeatureExtractor:
    """
    Извлекает вектор признаков для пары (user_inn, ste_candidate).
    Вызывается при каждом запросе — должен работать быстро.

    Все "тяжёлые" данные (user_ste, user_cat, seasonal) загружаются
    один раз при старте и хранятся в RAM в виде dict для O(1) lookup.
    """

    def __init__(
        self,
        user_ste_df:  Optional[pd.DataFrame] = None,
        user_cat:     Optional[dict]          = None,
        seasonal:     Optional[dict]          = None,
        global_pop:   Optional[dict]          = None,
    ):
        # Конвертируем DataFrame → dict  {(inn, ste_id) → {...}}
        self._uste: dict = {}
        if user_ste_df is not None:
            log.info("Индексирую user_ste_features ...")
            for row in user_ste_df.itertuples(index=False):
                key = (str(row.инн_заказчика), int(row.id_сте))
                self._uste[key] = {
                    "freq_30d":        int(row.freq_30d),
                    "freq_90d":        int(row.freq_90d),
                    "freq_365d":       int(row.freq_365d),
                    "days_since_last": int(row.days_since_last),
                    "avg_spend":       float(row.avg_spend),
                }
            log.info(f"  user_ste: {len(self._uste):,} пар")

        self._user_cat  = user_cat  or {}
        self._seasonal  = seasonal  or {}
        self._glob_pop  = global_pop or {}
        self._cur_month = datetime.now().month

    def extract(
        self,
        user_inn: str,
        candidate: dict,          # {ste_id, bm25_score, category}
        session:   dict | None,   # {clicks, bounces, dwells, added}
    ) -> np.ndarray:
        """Возвращает вектор float32 длины len(FEATURE_NAMES)."""
        ste_id = int(candidate["ste_id"])
        uste = self._uste.get((user_inn, ste_id), {})

        freq_30  = float(uste.get("freq_30d",        0))
        freq_90  = float(uste.get("freq_90d",        0))
        freq_365 = float(uste.get("freq_365d",       0))
        dsl      = float(uste.get("days_since_last", 9999))
        asp      = float(uste.get("avg_spend",       0.0))
        is_rep   = 1.0 if freq_365 > 0 else 0.0

        cat = candidate.get("category", "")
        cat_shares = self._user_cat.get(user_inn, {}).get("category_share", {})
        cat_share  = float(cat_shares.get(cat, 0.0))

        season = float(self._seasonal.get(ste_id, {}).get(self._cur_month, 0.5))
        glob_p = float(self._glob_pop.get(ste_id, 0.0))

        bm25 = float(candidate.get("bm25_score", 0.0))

        return np.array([
            bm25, freq_30, freq_90, freq_365,
            dsl, asp, cat_share,
            season, is_rep, glob_p,
        ], dtype=np.float32)

    def extract_batch(
        self,
        user_inn: str,
        candidates: list[dict],
        session: dict | None,
    ) -> np.ndarray:
        """Матрица [n × len(FEATURE_NAMES)] с нормализацией."""
        X = np.vstack([self.extract(user_inn, c, session) for c in candidates])
        # Нормируем BM25 (col 0) по батчу
        mx = X[:, 0].max()
        if mx > 0:
            X[:, 0] /= mx
        # days_since_last (col 4): инвертируем — меньше дней = лучше
        X[:, 4] = 1.0 / (1.0 + X[:, 4] / 30.0)
        # avg_spend (col 5): log-scale
        X[:, 5] = np.log1p(X[:, 5]) / 15.0
        return X


# ─────────────────────────────────────────────────────────────────────────────
# EXPLAIN ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class ExplainEngine:
    """
    Генерирует why_tags на основе значений признаков.
    Вызывается после rerank — теги объясняют, почему СТЕ оказалась на этой позиции.
    """

    def tags(
        self,
        user_inn:  str,
        candidate: dict,
        extractor: "FeatureExtractor",
        session:   dict | None,
    ) -> list[str]:
        ste_id = int(candidate["ste_id"])
        uste   = extractor._uste.get((user_inn, ste_id), {})
        tags: list[str] = []

        freq_365 = uste.get("freq_365d", 0)
        dsl      = uste.get("days_since_last", 9999)

        # Сигнал 1: история покупок
        if dsl < 30:
            tags.append("🔄 Покупали меньше месяца назад")
        elif freq_365 >= TAG_FREQUENT_THRESHOLD:
            tags.append(f"⭐ Часто покупаете ({freq_365}× за год)")
        elif freq_365 > 0:
            tags.append("📋 Есть в вашей истории")

        # Сигнал 2: сезон
        month  = extractor._cur_month
        season = extractor._seasonal.get(ste_id, {}).get(month, 0.5)
        if season >= 0.85:
            tags.append("📅 Сезонный спрос")

        # Сигнал 3: основная категория
        cat       = candidate.get("category", "")
        top_cats  = extractor._user_cat.get(user_inn, {}).get("top_categories", [])
        if cat and cat in top_cats[:2]:
            tags.append("🏢 Ваша основная категория")

        # Сигнал 4: сессионные клики
        if session and session.get("clicks", {}).get(str(ste_id)):
            tags.append("👁 Смотрели сегодня")

        return tags[:2]  # Максимум 2 в UI


# ─────────────────────────────────────────────────────────────────────────────
# RERANKER
# ─────────────────────────────────────────────────────────────────────────────

class Reranker:
    """
    Оркестрирует весь ML-пайплайн: признаки → LightGBM → explain → JSON.

    Fallback: если модель не загружена — возвращает кандидатов по BM25.
    Система НИКОГДА не падает из-за отсутствия ML-модели.
    """

    def __init__(self, extractor: FeatureExtractor, explainer: ExplainEngine):
        self._extractor = extractor
        self._explainer = explainer
        self._model     = None
        self._ready     = False
        self._bundle: dict = {}

    def load_model(self, path: Path) -> bool:
        try:
            with open(path, "rb") as f:
                self._model = pickle.load(f)
            self._ready = True
            log.info(f"LightGBM загружен: {path}")
            return True
        except FileNotFoundError:
            log.warning(f"LightGBM не найден: {path} — fallback BM25")
            return False

    def load_bundle(self, path: Path) -> None:
        if path.exists():
            with open(path, "rb") as f:
                self._bundle = pickle.load(f)
            log.info(f"Bundle загружен: {len(self._bundle):,} СТЕ")

    def rerank(
        self,
        user_inn:   str,
        candidates: list[dict],
        session:    dict | None = None,
        top_n:      int = FINAL_TOP_N,
    ) -> list[dict]:
        """
        Принимает топ-100 от BM25, возвращает персонализированный топ-20.

        Каждый результат содержит:
          ste_id, name, category,
          bm25_score, ml_score,
          why_tags,
          bundle: [{ste_id, name, conf}]
        """
        if not candidates:
            return []

        if self._ready:
            X      = self._extractor.extract_batch(user_inn, candidates, session)
            scores = self._model.predict(X)
        else:
            # Fallback: нормированный BM25 score
            bm_scores = np.array([c.get("bm25_score", 0.0) for c in candidates])
            mx = bm_scores.max() or 1
            scores = bm_scores / mx

        # ── Сессионный буст: применяем поверх ML-скора ───────────────────────
        # Не требует переобучения — простая добавка к готовому score.
        # Значения подобраны так, чтобы не «перебить» ML, но заметно влиять
        # на порядок при близких scores.
        if session:
            clicks    = session.get("clicks",  {})
            bounces   = session.get("bounces", {})
            dwells    = session.get("dwells",  {})
            purchases = session.get("added",   {})
            for i, c in enumerate(candidates):
                sid = str(c["ste_id"])
                if sid in purchases:
                    scores[i] += 0.50   # сильнейший сигнал — куплено в сессии
                elif sid in dwells and dwells[sid] > 5000:
                    scores[i] += 0.25   # долго смотрел карточку
                elif sid in clicks:
                    scores[i] += 0.15 * min(clicks[sid], 3)  # кликал (max ×3)
                if sid in bounces:
                    scores[i] -= 0.20   # быстро закрыл — не то

        # Сортировка
        order = np.argsort(-scores)[:top_n]

        results = []
        for rank, idx in enumerate(order):
            c = candidates[idx]
            why = self._explainer.tags(user_inn, c, self._extractor, session)
            results.append({
                "ste_id":    c["ste_id"],
                "name":      c.get("name", ""),
                "category":  c.get("category", ""),
                "bm25_score": round(float(c.get("bm25_score", 0)), 4),
                "ml_score":   round(float(scores[idx]), 4),
                "why_tags":  why,
                "bundle":    self._bundle.get(c["ste_id"], [])[:3],
                "is_ai_recommended": False,  # заполняется в API из query predictor
            })

        return results


# ─────────────────────────────────────────────────────────────────────────────
# ОБУЧЕНИЕ
# ─────────────────────────────────────────────────────────────────────────────

def train() -> dict:
    """
    Обучает LightGBM LambdaRank.
    Разбивка train/val — строго по ИНН (не по записям!).
    Возвращает метрики.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        log.error("lightgbm не установлен: pip install lightgbm"); sys.exit(1)

    if not TRAIN_DATASET_PKL.exists():
        log.error("Сначала запусти: python -m ml.pipeline"); sys.exit(1)

    log.info("Загружаю train_dataset ...")
    df = pd.read_parquet(TRAIN_DATASET_PKL)

    X = df[FEATURE_NAMES].fillna(0).astype(np.float32).values
    y = df["relevance"].astype(np.int32).values

    # Нормализация (те же операции что в FeatureExtractor.extract_batch)
    mx = X[:, 0].max()
    if mx > 0: X[:, 0] /= mx
    X[:, 4] = 1.0 / (1.0 + X[:, 4] / 30.0)
    X[:, 5] = np.log1p(X[:, 5]) / 15.0

    # Разбивка по ИНН
    inns = df["qid"].values
    unique_inns = list(dict.fromkeys(inns))
    rng = np.random.default_rng(42)
    n_val = max(1, int(len(unique_inns) * 0.2))
    val_inns = set(rng.choice(unique_inns, size=n_val, replace=False))

    tr_mask  = np.array([inn not in val_inns for inn in inns])
    val_mask = ~tr_mask

    from itertools import groupby
    def _grp(mask):
        return [sum(1 for _ in g)
                for _, g in groupby(inns[mask])]

    X_tr, y_tr = X[tr_mask],  y[tr_mask]
    X_vl, y_vl = X[val_mask], y[val_mask]
    g_tr = _grp(tr_mask); g_vl = _grp(val_mask)

    log.info(f"Train: {X_tr.shape[0]:,} | Val: {X_vl.shape[0]:,}")

    d_tr = lgb.Dataset(X_tr, label=y_tr, group=g_tr, feature_name=FEATURE_NAMES)
    d_vl = lgb.Dataset(X_vl, label=y_vl, group=g_vl, reference=d_tr)

    model = lgb.train(
        LGBM_PARAMS,
        d_tr,
        num_boost_round=LGBM_NUM_ROUNDS,
        valid_sets=[d_vl],
        callbacks=[
            lgb.early_stopping(LGBM_EARLY_STOPPING, verbose=True),
            lgb.log_evaluation(50),
        ],
    )

    with open(LGBM_MODEL_PKL, "wb") as f:
        pickle.dump(model, f, protocol=5)
    log.info(f"Модель сохранена: {LGBM_MODEL_PKL}")

    # Feature importance
    imp = dict(zip(model.feature_name(),
                   model.feature_importance(importance_type="gain")))
    log.info("Feature importance (gain):")
    for name, val in sorted(imp.items(), key=lambda x: -x[1])[:7]:
        log.info(f"  {name:22s}: {val:.1f}")

    metrics = _evaluate(model, X_vl, y_vl, g_vl,
                         X_tr=X_tr, y_tr=y_tr, g_tr=g_tr)
    return metrics


def _evaluate(model, X_vl, y_vl, g_vl,
              X_tr=None, y_tr=None, g_tr=None) -> dict:
    """NDCG@10 и MRR на validation, сравниваем с BM25 (col 0 после нормировки)."""
    def ndcg_k(ranked, rels, k=10):
        dcg  = sum(rels[i_] / np.log2(i + 2) for i, i_ in enumerate(ranked[:k]))
        idcg = sum(sorted(rels, reverse=True)[:k][i] / np.log2(i + 2)
                   for i in range(min(len(rels), k)))
        return dcg / idcg if idcg > 0 else 0.0

    def mrr(ranked, rels):
        for i, r in enumerate(ranked):
            if rels[r] >= 2:
                return 1.0 / (i + 1)
        return 0.0

    ml_scores  = model.predict(X_vl)
    bm25_col   = X_vl[:, 0]   # уже нормирован

    ndcg_ml, ndcg_bm, mrr_ml, mrr_bm = [], [], [], []
    pos = 0
    for sz in g_vl:
        if sz < 2:
            pos += sz; continue
        rels = y_vl[pos:pos + sz].tolist()
        ml_r = np.argsort(-ml_scores[pos:pos + sz]).tolist()
        bm_r = np.argsort(-bm25_col[pos:pos + sz]).tolist()
        ndcg_ml.append(ndcg_k(ml_r, rels))
        ndcg_bm.append(ndcg_k(bm_r, rels))
        mrr_ml.append(mrr(ml_r, rels))
        mrr_bm.append(mrr(bm_r, rels))
        pos += sz

    def _m(lst): return round(float(np.mean(lst)), 4) if lst else 0.0

    metrics = {
        "bm25_ndcg10":  _m(ndcg_bm), "bm25_mrr":   _m(mrr_bm),
        "lgbm_ndcg10":  _m(ndcg_ml), "lgbm_mrr":   _m(mrr_ml),
        "lift_pct": round((_m(ndcg_ml) - _m(ndcg_bm)) / max(_m(ndcg_bm), 1e-9) * 100, 1),
        "n_val_groups": len(g_vl),
    }

    log.info("=" * 45)
    log.info(f"  BM25 baseline  NDCG@10={metrics['bm25_ndcg10']:.4f}  MRR={metrics['bm25_mrr']:.4f}")
    log.info(f"  LightGBM       NDCG@10={metrics['lgbm_ndcg10']:.4f}  MRR={metrics['lgbm_mrr']:.4f}")
    log.info(f"  Lift           +{metrics['lift_pct']:.1f}%")
    log.info("=" * 45)
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", action="store_true",
                        help="Только оценка (без обучения)")
    args = parser.parse_args()

    log.info("=" * 55)
    if args.eval:
        log.info("PIPELINE  оценка LightGBM")
    else:
        log.info("PIPELINE  шаг 3/3: обучение LightGBM")
    log.info("=" * 55)

    if args.eval:
        if not LGBM_MODEL_PKL.exists():
            log.error("Модель не найдена. Сначала запусти без --eval"); sys.exit(1)
        df  = pd.read_parquet(TRAIN_DATASET_PKL)
        X   = df[FEATURE_NAMES].fillna(0).astype(np.float32).values
        y   = df["relevance"].astype(np.int32).values
        X[:, 0] /= (X[:, 0].max() or 1)
        X[:, 4]  = 1.0 / (1.0 + X[:, 4] / 30.0)
        X[:, 5]  = np.log1p(X[:, 5]) / 15.0
        inns = df["qid"].values
        from itertools import groupby
        groups = [sum(1 for _ in g) for _, g in groupby(inns)]
        with open(LGBM_MODEL_PKL, "rb") as f:
            model = pickle.load(f)
        _evaluate(model, X, y, groups)
    else:
        metrics = train()
        import json
        out = MODELS_DIR / "eval_results.json"
        with open(out, "w") as f:
            json.dump(metrics, f, indent=2)
        log.info(f"Метрики сохранены: {out}")
        log.info("✅  шаг 3/3 завершён — запускай api.main")


if __name__ == "__main__":
    main()
