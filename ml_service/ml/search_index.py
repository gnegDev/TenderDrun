"""
ml/search_index.py
==================
Скрипт 2 из 3. Запускается после ml.pipeline.

Что делает:
  1. Lemmatizes all СТЕ (pymorphy2)
  2. Строит spellcheck словарь (SymSpell)
  3. Строит BM25 индекс (rank_bm25)
  4. Обучает QueryPredictor на корпусе наименований
  5. Строит Word2Vec синонимы из корпуса СТЕ + контрактов → synonyms.json
  6. Строит Bundle-правила (Apriori на корзинах ИНН × месяц)

Запуск:
    python -m ml.search_index

Время: ~10–30 мин.
"""

import sys, re, json, pickle, logging
from collections import defaultdict, Counter
from pathlib import Path

import numpy as np
import pandas as pd
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):          # noqa: minimal fallback
        return it

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import *

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PREPROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

class Preprocessor:
    """Нормализация + лемматизация (pymorphy2). Fallback — split+lower."""

    STOPWORDS = {
        "и","в","на","с","по","для","из","к","от","до","у","за",
        "под","над","при","о","об","а","но","или","что","как","не",
        "это","то","все","он","она","они","шт","уп","пач","г","кг",
        "мл","л","мм","см","м","упак",
    }

    def __init__(self):
        try:
            try:
                import pymorphy3 as _morph_lib   # совместим с Python 3.10+
            except ImportError:
                import pymorphy2 as _morph_lib   # fallback для старых окружений
            self._morph = _morph_lib.MorphAnalyzer()
        except Exception as e:
            log.warning(f"Лемматизация отключена ({type(e).__name__}: {e})")
            self._morph = None
        self._lemma_cache: dict = {}  # кэш: слово → лемма

    def normalize(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\w\s\-]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def lemmatize_word(self, word: str) -> str:
        if self._morph is None or word in self.STOPWORDS:
            return word
        cached = self._lemma_cache.get(word)
        if cached is not None:
            return cached
        parsed = self._morph.parse(word)
        result = parsed[0].normal_form if parsed else word
        self._lemma_cache[word] = result
        return result

    def tokenize(self, text: str) -> list[str]:
        tokens = self.normalize(text).split()
        return [
            self.lemmatize_word(t)
            for t in tokens
            if t not in self.STOPWORDS and len(t) > 1
        ]

    def process(self, text: str) -> str:
        return " ".join(self.tokenize(text))


# ─────────────────────────────────────────────────────────────────────────────
# BM25 INDEX
# ─────────────────────────────────────────────────────────────────────────────

class BM25Index:
    """
    BM25+ индекс по каталогу СТЕ.

    Взвешивание полей (через повторение токенов):
      name     × 3  — самое важное
      category × 2
      specs    × 1

    Даёт O(n) поиск, где n = число слов в запросе.
    """

    def __init__(self, preprocessor: Preprocessor):
        self._prep    = preprocessor
        self._bm25    = None
        self._ste_ids: list = []
        self._names:   list = []
        self._cats:    list = []

    def build(self, ste_lookup: dict) -> None:
        try:
            import bm25s
        except ImportError:
            raise ImportError("Установи bm25s: pip install bm25s")
        log.info(f"Строю BM25 по {len(ste_lookup):,} СТЕ ...")
        corpus_tokens = []
        for ste_id, d in tqdm(ste_lookup.items(), desc="BM25 build"):
            self._ste_ids.append(ste_id)
            self._names.append(d["name"])
            self._cats.append(d["category"])
            tokens = (
                self._prep.tokenize(d["name"])      * 3 +
                self._prep.tokenize(d["category"])  * 2 +
                self._prep.tokenize(d["specs_raw"]) * 1
            )
            corpus_tokens.append(tokens or ["_empty_"])
        self._bm25 = bm25s.BM25(k1=BM25_K1, b=BM25_B)
        self._bm25.index(corpus_tokens)
        log.info("BM25 индекс построен")

    def search(self, query: str, top_k: int = 100) -> list[dict]:
        """Возвращает [{ste_id, name, category, bm25_score}, ...]."""
        if self._bm25 is None:
            raise RuntimeError("BM25 не загружен — запусти ml.search_index")
        tokens = self._prep.tokenize(query)
        return self._retrieve(tokens, top_k)

    def search_tokens(self, tokens: list[str], top_k: int = 100) -> list[dict]:
        """Принимает уже лемматизированные токены — без повторной токенизации."""
        if self._bm25 is None:
            raise RuntimeError("BM25 не загружен — запусти ml.search_index")
        return self._retrieve(tokens, top_k)

    def _retrieve(self, tokens: list[str], top_k: int) -> list[dict]:
        if not tokens:
            return []
        # Дедупликация: повторяющиеся токены не дают прироста качества BM25,
        # но линейно увеличивают время retrieval.
        tokens = list(dict.fromkeys(tokens))
        results, scores = self._bm25.retrieve([tokens], k=min(top_k, len(self._ste_ids)))
        doc_indices = results[0]
        doc_scores  = scores[0]
        return [
            {
                "ste_id":     self._ste_ids[idx],
                "name":       self._names[idx],
                "category":   self._cats[idx],
                "bm25_score": float(score),
            }
            for idx, score in zip(doc_indices, doc_scores)
            if score > 0
        ]

    def enrich_train_dataset_with_bm25(self, train_path: Path, ste_lookup: dict) -> None:
        """
        Проставляет реальные BM25-скоры в train_dataset.parquet.

        До вызова этой функции bm25_score=0.0 для всех строк.
        После — LightGBM получает честный текстовый сигнал релевантности.

        Для каждого ИНН (qid):
          1. Берём название наиболее часто купленной СТЕ как поисковый запрос.
          2. Прогоняем BM25 → top-100 кандидатов.
          3. Нормируем скоры [0, 1] и присваиваем строкам группы.

        Query-кэш: если два ИНН используют одинаковый запрос — BM25 вызывается
        только один раз.
        """
        if not train_path.exists():
            log.warning(f"train_dataset не найден: {train_path}")
            return

        log.info("Обогащаю train_dataset BM25-скорами ...")
        df = pd.read_parquet(train_path)
        bm25_col = np.zeros(len(df), dtype=np.float32)

        query_cache: dict = {}   # query_text → {ste_id: norm_score}

        for qid, grp in tqdm(df.groupby("qid"), desc="BM25 enrich", mininterval=5):
            pos = grp[grp["relevance"] == 3]
            if pos.empty:
                continue
            best_ste_id = int(pos.nlargest(1, "freq_365d")["id_сте"].values[0])
            query = ste_lookup.get(best_ste_id, {}).get("name", "")
            if not query or len(query) < 3:
                continue

            if query not in query_cache:
                candidates = self.search(query, top_k=BM25_TOP_K)
                if candidates:
                    max_s = max(c["bm25_score"] for c in candidates) or 1.0
                    query_cache[query] = {
                        c["ste_id"]: c["bm25_score"] / max_s for c in candidates
                    }
                else:
                    query_cache[query] = {}

            score_map = query_cache[query]
            for row_idx, ste_id in zip(grp.index, grp["id_сте"]):
                bm25_col[row_idx] = score_map.get(int(ste_id), 0.0)

        df["bm25_score"] = bm25_col
        df.to_parquet(train_path, index=False)
        non_zero = int((bm25_col > 0).sum())
        log.info(f"  BM25-скоры: {non_zero:,}/{len(df):,} строк ненулевые "
                 f"({non_zero / max(len(df), 1):.1%})")

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"bm25": self._bm25, "ids": self._ste_ids,
                         "names": self._names, "cats": self._cats}, f, protocol=5)
        log.info(f"BM25 сохранён: {path}")

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            d = pickle.load(f)
        self._bm25    = d["bm25"]
        self._ste_ids = d["ids"]
        self._names   = d["names"]
        self._cats    = d["cats"]
        log.info(f"BM25 загружен: {len(self._ste_ids):,} СТЕ")


# ─────────────────────────────────────────────────────────────────────────────
# SPELLCHECKER
# ─────────────────────────────────────────────────────────────────────────────

class SpellChecker:
    """SymSpell, O(1) коррекция опечаток."""

    def __init__(self):
        self._sym = None

    def build_dict(self, ste_lookup: dict, out_path: Path) -> None:
        counts: Counter = Counter()
        for d in ste_lookup.values():
            for w in re.findall(r"\w+", d["name"].lower()):
                if len(w) >= 2:
                    counts[w] += 1
        with open(out_path, "w", encoding="utf-8") as f:
            for w, c in counts.most_common():
                f.write(f"{w} {c}\n")
        log.info(f"Словарь SymSpell: {len(counts):,} слов → {out_path}")

    def load(self, path: Path) -> None:
        """Загружает словарь SymSpell из UTF-8 файла (работает на любой платформе)."""
        try:
            from symspellpy import SymSpell, Verbosity
            self._sym = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
            # Читаем файл вручную, чтобы избежать проблем с кодировкой
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        word = parts[0]
                        try:
                            count = int(parts[1])
                        except ValueError:
                            continue
                        self._sym.create_dictionary_entry(word, count)
            self._Verbosity = Verbosity
            log.info(f"SymSpell загружен: {path}")
        except ImportError:
            log.warning("symspellpy не установлен — исправление опечаток отключено")
        except Exception as e:
            log.warning(f"Ошибка загрузки SymSpell: {e}")

    def correct(self, query: str) -> tuple[str, bool]:
        if self._sym is None:
            return query, False
        words, fixed_any = [], False
        for w in query.split():
            # SymSpell словарь строился в lowercase — приводим к тому же виду
            w_lower = w.lower()
            sugg = self._sym.lookup(w_lower, self._Verbosity.CLOSEST, max_edit_distance=2)
            if sugg and sugg[0].term != w_lower:
                words.append(sugg[0].term)
                fixed_any = True
            else:
                words.append(w_lower)
        return " ".join(words), fixed_any


# ─────────────────────────────────────────────────────────────────────────────
# SYNONYM EXPANDER
# ─────────────────────────────────────────────────────────────────────────────

class SynonymExpander:
    """Расширяет запрос синонимами из ручного словаря + Word2Vec (строится при индексации)."""

    # Ручной словарь закупочных терминов (покрывает частые случаи без ML).
    # Значения — ИНФИНИТИВНЫЕ / ИМЕНИТЕЛЬНЫЙ формы: expand() пропускает их
    # через Preprocessor.tokenize(), поэтому склонения не важны.
    MANUAL: dict = {
        # Оргтехника
        "мфу":             ["принтер", "многофункциональный устройство"],
        "принтер":         ["мфу", "многофункциональный устройство"],
        "картридж":        ["тонер", "тонер-картридж", "чернила"],
        "тонер":           ["картридж", "тонер-картридж"],
        "монитор":         ["дисплей", "экран", "жк монитор"],
        "дисплей":         ["монитор", "экран"],
        "компьютер":       ["пк", "системный блок", "персональный компьютер"],
        "ноутбук":         ["лэптоп", "портативный компьютер"],
        "флешка":          ["usb накопитель", "флэш накопитель", "флеш накопитель"],
        "флэш":            ["флешка", "usb накопитель", "накопитель"],
        "флеш":            ["флешка", "usb накопитель", "флэш накопитель"],
        "клавиатура":      ["клавиатура проводной", "клавиатура беспроводной"],
        "мышь":            ["манипулятор мышь", "мышь компьютерный", "мышка"],
        "мышка":           ["мышь", "манипулятор мышь"],
        # Бумага и расходники
        "бумага":          ["бумага офисный", "бумага а4", "бумага а3"],
        "тетрадь":         ["тетрадь школьный", "тетрадь клетка", "тетрадь линейка"],
        "ручка":           ["авторучка", "шариковый ручка"],
        "карандаш":        ["карандаш простой", "карандаш чернографитный"],
        "папка":           ["папка скоросшиватель", "папка файл", "скоросшиватель"],
        "скотч":           ["лента клейкий", "лента скотч"],
        # Мебель
        "стул":            ["стул офисный", "кресло офисный"],
        "кресло":          ["кресло офисный", "стул офисный", "кресло руководитель"],
        "стол":            ["стол офисный", "стол письменный"],
        "шкаф":            ["шкаф офисный", "шкаф документ", "тумба"],
        "стеллаж":         ["стеллаж металлический", "полка", "полка металлический"],
        # Медицина и СИЗ
        "перчатки":        ["перчатки медицинский", "перчатки латексный", "перчатки нитриловый"],
        "маска":           ["маска медицинский", "респиратор", "маска защитный"],
        "респиратор":      ["маска медицинский", "маска защитный"],
        "бахилы":          ["бахилы медицинский", "бахилы полиэтиленовый"],
        "антисептик":      ["дезинфектант", "санитайзер", "дезинфицирующий средство"],
        "дезинфектант":    ["антисептик", "санитайзер", "дезинфицирующий средство"],
        "санитайзер":      ["антисептик", "дезинфектант"],
        "мыло":            ["мыло жидкий", "мыло туалетный", "мыло хозяйственный"],
        # Уборка и хозтовары
        "моющее":          ["чистящий средство", "средство мытьё"],
        "мешок":           ["мешок мусор", "пакет мусор"],
        "пакет":           ["пакет мусорный", "мешок мусор"],
        "швабра":          ["швабра отжим", "моп", "швабра мытьё"],
        "тряпка":          ["салфетка уборочный", "ветошь"],
        # Продукты питания
        "чай":             ["чай чёрный", "чай зелёный", "чай листовой"],
        "кофе":            ["кофе молотый", "кофе растворимый", "кофе зерно"],
        "сахар":           ["сахар белый", "сахар рафинад", "сахар-песок"],
        # Стройматериалы
        "доска":           ["доска обрезной", "доска строганый", "пиломатериал"],
        "цемент":          ["цемент м400", "цемент м500", "смесь цементный"],
        "краска":          ["краска водоэмульсионный", "краска акриловый", "лкм"],
        # Медоборудование
        "шприц":           ["шприц одноразовый", "шприц медицинский"],
        "бинт":            ["бинт стерильный", "бинт нестерильный", "перевязочный материал"],
        # IT / Сети
        "кабель":          ["кабель витой пара", "кабель сетевой", "провод"],
        "роутер":          ["маршрутизатор", "коммутатор", "свитч"],
        "коммутатор":      ["свитч", "роутер", "маршрутизатор"],
        "свитч":           ["коммутатор", "маршрутизатор"],
        "сервер":          ["сервер rack", "серверный оборудование"],
        "ups":             ["ибп", "источник бесперебойный питание"],
        "ибп":             ["ups", "источник бесперебойный питание"],
    }

    def __init__(self, synonyms_path: Path | None = None, preprocessor=None):
        # Ручной словарь имеет приоритет — автоматические синонимы его не перезаписывают
        self._prep = preprocessor   # Preprocessor для лемматизации токенов синонимов
        self._syns = {}
        if synonyms_path and synonyms_path.exists():
            with open(synonyms_path, encoding="utf-8") as f:
                self._syns.update(json.load(f))
            # MANUAL перезаписывает автоматические для ключевых терминов
            self._syns.update(self.MANUAL)
            log.info(f"Синонимы загружены: {len(self._syns):,} слов (Word2Vec + ручной словарь)")
        else:
            self._syns.update(self.MANUAL)

    # Максимум дополнительных токенов от синонимов на весь запрос.
    # Для типичного запроса 2-3 слова это никогда не достигается (добавляется 3-6).
    # Ограничение защищает от раздувания длинных запросов до 50+ токенов,
    # что замедляет bm25s без прироста качества.
    MAX_SYN_EXTRA_TOKENS = 8

    def _tokenize_syn(self, syn: str) -> list[str]:
        """Токенизирует строку синонима через тот же Preprocessor, что и BM25-индекс.
        Без лемматизации формы типа 'витая' не совпадут с леммой 'витой' в индексе."""
        if self._prep is not None:
            return self._prep.tokenize(syn)
        return [t for t in syn.lower().split() if t]

    def expand(self, tokens: list[str]) -> tuple[list[str], list[str]]:
        """
        Возвращает (расширенные_токены, добавленные_синонимы).
        Синонимы добавляются в токены запроса — BM25 взвешивает их сам.
        Лимит MAX_SYN_EXTRA_TOKENS защищает от раздувания длинных запросов.
        Дедупликация: токены, уже присутствующие в запросе или добавленные
        ранее другим синонимом, не добавляются повторно — иначе BM25 получает
        искусственный перевес одного слова.
        """
        expanded = list(tokens)
        seen = set(tokens)        # уже присутствующие токены
        added: list[str] = []
        extra = 0
        for t in tokens:
            if extra >= self.MAX_SYN_EXTRA_TOKENS:
                break
            for syn in self._syns.get(t, []):
                syn_tok = self._tokenize_syn(syn)
                if not syn_tok:
                    continue
                new_tok = [tk for tk in syn_tok if tk not in seen]
                if not new_tok:
                    continue
                if extra + len(new_tok) > self.MAX_SYN_EXTRA_TOKENS:
                    continue
                expanded.extend(new_tok)
                seen.update(new_tok)
                added.append(syn)
                extra += len(new_tok)
        return expanded, added


# ─────────────────────────────────────────────────────────────────────────────
# QUERY PREDICTOR  ("AI рекомендует")
# ─────────────────────────────────────────────────────────────────────────────

class QueryPredictor:
    """
    Предсказывает завершение запроса в реальном времени (от 3 символов).

    Топ-1 предсказание с score ≥ AI_SCORE_THRESHOLD отображается
    в UI ВЫШЕ всех остальных вариантов с меткой "AI рекомендует".

    Архитектура:
      - prefix-индекс: первые 1–4 символа → список (запрос, частота)
      - bigram-модель: последний токен → вероятный следующий токен
      - персонализация: буст для запросов из истории ИНН
      - сессионный буст: недавние запросы пользователя → +0.25

    Обучается на корпусе:
      - наименования СТЕ    (вес 1)
      - названия контрактов (вес 2, отражают реальные запросы заказчиков)
    """

    def __init__(self):
        self._freq:   dict = {}           # query → частота
        self._prefix: dict = defaultdict(list)  # prefix → [(query, freq)]
        self._bigrams: dict = defaultdict(Counter)
        self._fitted  = False

    def fit(self, ste_names: list[str], contract_names: list[str]) -> "QueryPredictor":
        log.info("Обучаю QueryPredictor ...")
        freq: dict = defaultdict(int)

        def _add(text: str, weight: int):
            t = re.sub(r"[^\w\s]", " ", text.lower()).strip()
            t = re.sub(r"\s+", " ", t)
            if len(t) >= 3:
                freq[t] += weight

        for n in tqdm(ste_names,      desc="STE names",      mininterval=2):
            _add(n, 1)
        for n in tqdm(contract_names, desc="Contract names",  mininterval=2):
            _add(n, 2)

        self._freq = dict(freq)

        # Prefix-индекс (ключи длиной 1–4)
        log.info("  Строю prefix-индекс ...")
        pfx: dict = defaultdict(list)
        for q, f in self._freq.items():
            for l in range(1, min(5, len(q) + 1)):
                pfx[q[:l]].append((q, f))
        # Сортируем один раз офлайн
        self._prefix = {k: sorted(v, key=lambda x: -x[1])[:60] for k, v in pfx.items()}

        # Bigrams
        log.info("  Строю bigrams ...")
        for q, f in self._freq.items():
            toks = q.split()
            for i in range(len(toks) - 1):
                self._bigrams[toks[i]][toks[i + 1]] += f

        self._fitted = True
        log.info(f"  QueryPredictor: {len(self._freq):,} запросов")
        return self

    def suggest(
        self,
        prefix: str,
        user_inn: str | None = None,
        user_cat: dict | None = None,
        session_queries: list[str] | None = None,
        session_vocab: set | None = None,
        top_n: int = 5,
    ) -> dict:
        """
        Главный метод. Вызывается из /suggest endpoint.

        session_vocab — множество лемм из названий СТЕ, на которые
        пользователь кликал/покупал в текущей сессии. Вычисляется в API
        из Redis-сессии и передаётся сюда. Позволяет динамически поднимать
        подсказки, содержащие «горячие» слова сессии.

        Возвращает:
        {
          "suggestions": [
            {"query": "...", "score": 0.91, "is_ai_recommended": true,  "source": "session"},
            {"query": "...", "score": 0.62, "is_ai_recommended": false, "source": "popular"},
          ],
          "ai_recommended_query": "перчатки медицинские"  // или null
        }
        """
        if not self._fitted or len(prefix.strip()) < QUERY_MIN_CHARS:
            return {"suggestions": [], "ai_recommended_query": None}

        pfx = re.sub(r"[^\w\s]", " ", prefix.lower()).strip()

        # ── Кандидаты ────────────────────────────────────────────────────────
        cands: dict = {}
        for l in range(min(4, len(pfx)), 0, -1):
            key = pfx[:l]
            for q, f in self._prefix.get(key, []):
                if q not in cands:
                    cands[q] = {"freq": f, "pm": l / len(pfx)}
            if cands:
                break

        # Fallback: substring match
        if len(cands) < top_n * 2:
            for q in self._freq:
                if q not in cands and pfx in q:
                    cands[q] = {"freq": self._freq[q], "pm": 0.4}
                if len(cands) >= top_n * 8:
                    break

        if not cands:
            return {"suggestions": [], "ai_recommended_query": None}

        # ── Scoring ──────────────────────────────────────────────────────────
        max_f = max(c["freq"] for c in cands.values()) or 1
        session_set = set(
            re.sub(r"[^\w\s]", " ", q.lower()).strip()
            for q in (session_queries or [])
        )
        cat_words = set()
        if user_cat and user_inn:
            for cat in user_cat.get(user_inn, {}).get("top_categories", [])[:3]:
                cat_words.update(cat.lower().split())

        sv = session_vocab or set()   # «горячий словарь» текущей сессии

        scored: list = []
        for q, meta in cands.items():
            pop   = meta["freq"] / max_f
            pm    = meta["pm"]
            sess  = 0.25 if q in session_set else 0.0
            catb  = 0.10 if any(w in q for w in cat_words) else 0.0
            # буст за слова из кликнутых/купленных СТЕ в этой сессии
            vocb  = 0.20 if any(w in q for w in sv) else 0.0
            score = 0.40 * pop + 0.20 * pm + 0.15 * sess + 0.10 * catb + 0.15 * vocb
            src   = "session" if (sess or vocb) else ("category" if catb else "popular")
            scored.append((score, q, src))

        scored.sort(key=lambda x: -x[0])
        top = scored[:top_n]

        ai_query = None
        suggestions = []
        for rank, (score, q, src) in enumerate(top):
            is_ai = rank == 0 and score >= QUERY_AI_THRESH
            if is_ai:
                ai_query = q
            suggestions.append({
                "query": q, "score": round(score, 3),
                "source": src, "is_ai_recommended": is_ai,
            })

        return {"suggestions": suggestions, "ai_recommended_query": ai_query}

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({
                "freq": self._freq,
                "prefix": dict(self._prefix),
                "bigrams": dict(self._bigrams),
                "fitted": self._fitted,
            }, f, protocol=5)
        log.info(f"QueryPredictor сохранён: {path}")

    def load(self, path: Path) -> "QueryPredictor":
        with open(path, "rb") as f:
            d = pickle.load(f)
        self._freq    = d["freq"]
        self._prefix  = defaultdict(list, d["prefix"])
        self._bigrams = defaultdict(Counter, d["bigrams"])
        self._fitted  = d["fitted"]
        log.info(f"QueryPredictor загружен: {len(self._freq):,} запросов")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# BUNDLE RECOMMENDER  ("Часто берут вместе")
# ─────────────────────────────────────────────────────────────────────────────

class BundleRecommender:
    """
    Ассоциативные правила (Apriori).
    Корзина = все СТЕ одного ИНН за один месяц.
    """

    def __init__(self):
        self._rules: dict = {}   # ste_id → [{ste_id, conf, lift}, ...]

    def build(self, df_contracts: pd.DataFrame, ste_lookup: dict) -> None:
        try:
            from mlxtend.frequent_patterns import apriori, association_rules
            from mlxtend.preprocessing import TransactionEncoder
        except ImportError:
            log.warning("mlxtend не установлен — bundle отключён")
            return

        log.info("Строю Bundle (Apriori) ...")
        df = df_contracts.copy()
        if df["дата_контракта"].dt.tz is not None:
            df["дата_контракта"] = df["дата_контракта"].dt.tz_convert(None)
        df["basket_key"] = (
            df["инн_заказчика"].astype(str) + "_"
            + df["дата_контракта"].dt.to_period("M").astype(str)
        )

        # Топ-3000 СТЕ по частоте (Apriori медленный на больших данных)
        popular = set(df["id_сте"].value_counts().head(3000).index)
        baskets = (
            df[df["id_сте"].isin(popular)]
            .groupby("basket_key")["id_сте"]
            .apply(lambda x: list(set(x.astype(str))))
            .reset_index(name="items")
        )
        baskets = baskets[baskets["items"].apply(len) >= 2]["items"].tolist()

        if not baskets:
            log.warning("  Недостаточно данных для Apriori"); return

        te = TransactionEncoder()
        te_arr = te.fit_transform(baskets)
        df_te  = pd.DataFrame(te_arr, columns=te.columns_)

        freq = apriori(df_te, min_support=BUNDLE_MIN_SUPPORT, use_colnames=True)
        if freq.empty:
            log.warning("  Apriori: нет частых наборов"); return

        rules = association_rules(freq, metric="confidence",
                                  min_threshold=BUNDLE_MIN_CONFIDENCE)
        for _, row in rules.iterrows():
            ant = list(row["antecedents"]); con = list(row["consequents"])
            if len(ant) != 1 or len(con) != 1:
                continue
            x, y = int(ant[0]), int(con[0])
            self._rules.setdefault(x, []).append({
                "ste_id": y,
                "name":   ste_lookup.get(y, {}).get("name", ""),
                "conf":   round(float(row["confidence"]), 3),
                "lift":   round(float(row["lift"]), 3),
            })

        for k in self._rules:
            self._rules[k] = sorted(self._rules[k], key=lambda r: -r["lift"])[:BUNDLE_TOP_N]

        log.info(f"  Bundle rules: {len(self._rules):,} СТЕ")

    def get(self, ste_id) -> list[dict]:
        """Поддерживает и int, и str ste_id — ключи могут отличаться в зависимости от данных."""
        r = self._rules.get(ste_id)
        if r is None:
            r = self._rules.get(int(ste_id) if isinstance(ste_id, str) and ste_id.isdigit() else str(ste_id))
        return r or []

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self._rules, f, protocol=5)

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            self._rules = pickle.load(f)
        log.info(f"Bundle загружен: {len(self._rules):,} СТЕ")


# ─────────────────────────────────────────────────────────────────────────────
# PRICE ANALOGUE INDEX
# ─────────────────────────────────────────────────────────────────────────────

class PriceAnalogueIndex:
    """
    Для каждой СТЕ хранит до ANALOGUE_TOP_N аналогов с более низкой ценой
    в той же категории.

    Строится один раз при 02_build_index.py (~2-5 мин).
    Запрос — O(1) dict-lookup, нулевой вклад в latency.

    Алгоритм:
      1. Группируем СТЕ по категории.
      2. Для каждой СТЕ X с ценой P ищем в той же категории СТЕ Y с P_Y < P.
      3. Считаем Jaccard-сходство лемматизированных токенов названий.
      4. Финальный score = 0.6 × jaccard + 0.4 × (P - P_Y) / P.
         Это баланс между «похоже» и «сильно дешевле».
      5. Берём топ-ANALOGUE_TOP_N по score.
    """

    def __init__(self):
        self._index: dict = {}   # ste_id → [{"ste_id", "name", "category",
                                 #             "median_price", "savings_pct"}, ...]

    def build(self, ste_lookup: dict, prep: Preprocessor) -> None:
        log.info("Строю PriceAnalogueIndex ...")

        # Шаг 1: токенизируем названия (только для СТЕ с ценой)
        tokenized: dict = {}
        for ste_id, info in ste_lookup.items():
            if info.get("median_price", 0) > 0:
                tokenized[ste_id] = frozenset(prep.tokenize(info["name"]))

        # Шаг 2: группируем по категории
        from collections import defaultdict
        cat_items: dict = defaultdict(list)
        for ste_id, info in ste_lookup.items():
            if ste_id not in tokenized:
                continue
            cat_items[info["category"]].append(
                (ste_id, info["median_price"], tokenized[ste_id])
            )

        total_with_analogues = 0

        # Шаг 3: для каждой СТЕ ищем дешёвые аналоги в той же категории
        for cat, items in tqdm(cat_items.items(), desc="Price analogues"):
            if len(items) < 2:
                continue

            for sid, price, tok_a in items:
                if not tok_a:
                    continue
                candidates = []

                for other_sid, other_price, tok_b in items:
                    if other_sid == sid or other_price >= price:
                        continue
                    if not tok_b:
                        continue
                    union = tok_a | tok_b
                    if not union:
                        continue
                    jaccard = len(tok_a & tok_b) / len(union)
                    if jaccard < ANALOGUE_MIN_JACCARD:
                        continue
                    savings = (price - other_price) / price
                    score   = 0.6 * jaccard + 0.4 * savings
                    candidates.append((score, other_sid, other_price, savings))

                if candidates:
                    candidates.sort(reverse=True)
                    self._index[sid] = [
                        {
                            "ste_id":       a[1],
                            "name":         ste_lookup[a[1]]["name"],
                            "category":     ste_lookup[a[1]]["category"],
                            "median_price": round(a[2], 2),
                            "savings_pct":  round(a[3] * 100, 1),
                        }
                        for a in candidates[:ANALOGUE_TOP_N]
                    ]
                    total_with_analogues += 1

        log.info(
            f"PriceAnalogueIndex: {total_with_analogues:,} СТЕ имеют аналоги "
            f"(из {len(tokenized):,} с ценой)"
        )

    def get(self, ste_id) -> list[dict]:
        """Поддерживает и int, и str ste_id — ключи могут отличаться в зависимости от данных."""
        r = self._index.get(ste_id)
        if r is None:
            r = self._index.get(int(ste_id) if isinstance(ste_id, str) and ste_id.isdigit() else str(ste_id))
        return r or []

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self._index, f, protocol=5)

    def load(self, path: Path) -> None:
        with open(path, "rb") as f:
            self._index = pickle.load(f)
        log.info(f"PriceAnalogueIndex загружен: {len(self._index):,} СТЕ")


# ─────────────────────────────────────────────────────────────────────────────
# ФАСАД SearchEngine
# ─────────────────────────────────────────────────────────────────────────────

class SearchEngine:
    """
    Фасад: объединяет BM25 + SpellChecker + SynonymExpander.
    Загружается в API как синглтон.
    """

    def __init__(self):
        self.prep     = Preprocessor()
        self.bm25     = BM25Index(self.prep)
        self.spell    = SpellChecker()
        self.synonyms = SynonymExpander(preprocessor=self.prep)

    def load_all(self) -> None:
        if BM25_INDEX_PKL.exists():
            self.bm25.load(BM25_INDEX_PKL)
        else:
            log.warning("BM25 не найден — запусти ml.search_index")
        if SPELLCHECK_DICT_PATH.exists():
            self.spell.load(SPELLCHECK_DICT_PATH)
        if SYNONYMS_JSON.exists():
            self.synonyms = SynonymExpander(SYNONYMS_JSON, preprocessor=self.prep)

    def search(self, query: str, top_k: int = BM25_TOP_K) -> tuple[list[dict], dict]:
        """
        Возвращает (candidates, analysis).
        analysis = {corrected, was_corrected, synonyms_added}

        Стратегия:
          1. Пробуем скорректированный запрос.
          2. Если BM25 даёт 0 результатов — откатываемся к оригиналу.
          3. Если всё равно 0 — ищем по каждому токену отдельно и объединяем.
        """
        corrected, was_corrected = self.spell.correct(query)
        tokens = self.prep.tokenize(corrected)
        exp_tok, syns_added = self.synonyms.expand(tokens)
        candidates = self.bm25.search_tokens(exp_tok, top_k=top_k)

        # Fallback 1: коррекция привела в другую семантическую область — пробуем оригинал
        if not candidates and was_corrected:
            orig_tokens = self.prep.tokenize(query)
            orig_exp, orig_syns = self.synonyms.expand(orig_tokens)
            orig_candidates = self.bm25.search_tokens(orig_exp, top_k=top_k)
            if orig_candidates:
                candidates, exp_tok, syns_added = orig_candidates, orig_exp, orig_syns
                corrected, was_corrected = query, False

        # Fallback 2: всё ещё 0 — ищем по каждому токену отдельно
        if not candidates:
            seen: set = set()
            for tok in (exp_tok or self.prep.tokenize(query)):
                for c in self.bm25.search_tokens([tok], top_k=top_k):
                    if c["ste_id"] not in seen:
                        seen.add(c["ste_id"])
                        candidates.append(c)

        analysis = {
            "original":       query,
            "corrected":      corrected if was_corrected else None,
            "was_corrected":  was_corrected,
            "synonyms_added": syns_added,
        }
        return candidates, analysis


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=" * 55)
    log.info("PIPELINE  шаг 2/3: поисковый индекс")
    log.info("=" * 55)

    if not STE_LOOKUP_PKL.exists():
        log.error("Сначала запусти: python -m ml.pipeline"); sys.exit(1)

    with open(STE_LOOKUP_PKL, "rb") as f:
        ste_lookup = pickle.load(f)

    prep = Preprocessor()

    # 1. Spellcheck dict
    sc = SpellChecker()
    sc.build_dict(ste_lookup, SPELLCHECK_DICT_PATH)
    sc.load(SPELLCHECK_DICT_PATH)

    # 2. BM25
    idx = BM25Index(prep)
    idx.build(ste_lookup)
    idx.save(BM25_INDEX_PKL)

    # 2.1 Обогащаем train_dataset реальными BM25-скорами (если уже создан шагом 1)
    if TRAIN_DATASET_PKL.exists():
        idx.enrich_train_dataset_with_bm25(TRAIN_DATASET_PKL, ste_lookup)
    else:
        log.warning("train_dataset не найден — запусти 01_pipeline.py перед 02_build_index.py")

    # 3. QueryPredictor
    df_c = pd.read_csv(
        CONTRACTS_CSV, sep=";", names=CONTRACTS_COLS,
        encoding="utf-8-sig", usecols=["название_контракта"],
    )
    contract_names = df_c["название_контракта"].dropna().tolist()
    ste_names      = [d["name"] for d in ste_lookup.values()]

    qp = QueryPredictor()
    qp.fit(ste_names, contract_names)
    qp.save(QUERY_PREDICTOR_PKL)

    # 4. Word2Vec синонимы (строятся из корпуса СТЕ + контрактов)
    try:
        from gensim.models import Word2Vec
        log.info("Обучаю Word2Vec синонимы ...")

        # Корпус: наименования СТЕ (вес ×1) + названия контрактов (вес ×2)
        ste_tokens  = [prep.tokenize(d["name"]) for d in ste_lookup.values()]
        cont_tokens = [prep.tokenize(n) for n in contract_names]
        corpus = [s for s in (ste_tokens + cont_tokens * 2) if len(s) >= 2]

        w2v = Word2Vec(
            sentences=corpus,
            vector_size=64,   # небольшой вектор → быстро, но достаточно точно
            window=4,         # закупочные фразы короткие, window=4 оптимален
            min_count=5,      # игнорировать редкие слова (< 5 появлений)
            epochs=10,
            workers=4,
            sg=1,             # Skip-Gram лучше на малом корпусе, чем CBOW
        )

        # Строим словарь: слово → [синоним1, синоним2, синоним3]
        # Берём только слова длиной ≥ 3 символа и с cosine similarity ≥ 0.65
        SIM_THRESHOLD = 0.65
        manual_words  = set(SynonymExpander.MANUAL.keys())
        syns: dict    = {}
        vocab         = [w for w in w2v.wv.key_to_index if len(w) >= 3]

        for w in vocab:
            candidates = [
                s for s, score in w2v.wv.most_similar(w, topn=10)
                if s != w and len(s) >= 3 and score >= SIM_THRESHOLD
            ][:3]
            if candidates:
                # Не перезаписывать ручной словарь автоматическими синонимами
                if w not in manual_words:
                    syns[w] = candidates

        with open(SYNONYMS_JSON, "w", encoding="utf-8") as f:
            json.dump(syns, f, ensure_ascii=False, indent=2)
        log.info(f"Синонимы Word2Vec: {len(syns):,} слов → {SYNONYMS_JSON}")
    except Exception as e:
        log.warning(f"Word2Vec пропущен ({e}) — используем ручной словарь")

    # 5. Bundle
    df_contracts = pd.read_csv(
        CONTRACTS_CSV, sep=";", names=CONTRACTS_COLS,
        encoding="utf-8-sig", parse_dates=["дата_контракта"],
        dtype={"id_сте": "int32", "инн_заказчика": "str"},
    )
    df_contracts = df_contracts.dropna(subset=["инн_заказчика", "id_сте"])
    bundle = BundleRecommender()
    bundle.build(df_contracts, ste_lookup)
    bundle.save(BUNDLE_RULES_PKL)

    # 6. Price Analogue Index
    price_idx = PriceAnalogueIndex()
    price_idx.build(ste_lookup, prep)
    price_idx.save(PRICE_ANALOGUES_PKL)

    log.info("=" * 55)
    log.info("✅  шаг 2/3 завершён — запускай ml.ranker")
    log.info("=" * 55)


if __name__ == "__main__":
    main()