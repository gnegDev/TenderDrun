# TenderDrun — персонализированный поиск СТЕ

Веб-приложение для поиска стандартизированных товарных единиц (СТЕ) в системе государственных закупок. Учитывает историю закупок заказчика, исправляет опечатки, расширяет запрос синонимами и персонализирует выдачу через ML-модель в реальном времени.

---

## Системные требования

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| Docker | 24+ | 25+ |
| Docker Compose | 2.20+ | 2.24+ |
| RAM | 4 GB | 8 GB |
| Диск | 10 GB | 20 GB |
| OS | Linux / macOS / Windows (WSL2) | Linux |

> Для локальной разработки без Docker дополнительно нужны: Python 3.11+, PostgreSQL 15, Redis 7.

---

## Быстрый старт (Docker)

### 1. Клонировать репозиторий

```bash
git clone <repo-url>
cd app
```

### 2. Положить CSV-файлы данных

```
app/data/
├── СТЕ_<дата>.csv
└── Контракты_<дата>.csv
```

Файлы не входят в репозиторий. Кодировка: UTF-8-BOM, разделитель `;`, без заголовков.

### 3. Собрать и запустить

```bash
docker compose up --build
```

Сервисы поднимаются в правильном порядке автоматически (healthcheck). Первый запуск занимает 2–4 минуты (сборка образов, загрузка ML-моделей).

| URL | Описание |
|---|---|
| http://localhost:8080 | Веб-интерфейс |
| http://localhost:8080/docs | Swagger UI (FastAPI) |
| http://localhost:8001/health | Статус ML-сервиса |
| http://localhost:8001/metrics | Метрики модели (NDCG, latency) |

### 4. Остановить

```bash
docker compose down          # сохраняет данные БД
docker compose down -v       # удаляет том postgres_data (полный сброс)
```

---

## Импорт данных из CSV

База создаётся автоматически при старте backend. Загрузка данных выполняется отдельным скриптом — после того, как БД уже запущена.

### Через Docker (рекомендуется)

```bash
# Запустить только БД
docker compose up -d db

# Дождаться готовности БД (healthcheck)
docker compose ps

# Загрузить данные
docker compose run --rm backend python /app/../scripts/load_data.py \
  --ste "/app/../data/СТЕ_20260403.csv" \
  --contracts "/app/../data/Контракты_20260403.csv"
```

### Напрямую (локально)

```bash
# БД должна быть доступна на localhost:5432
source .venv/bin/activate

python scripts/load_data.py \
  --ste "data/СТЕ_20260403.csv" \
  --contracts "data/Контракты_20260403.csv"
```

Переопределить адрес БД:

```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/hackathon \
  python scripts/load_data.py --ste data/СТЕ_*.csv --contracts data/Контракты_*.csv
```

### Параметры скрипта

| Параметр | Описание |
|---|---|
| `--ste <path>` | Путь к CSV-файлу СТЕ (поддерживает glob: `data/СТЕ_*.csv`) |
| `--contracts <path>` | Путь к CSV-файлу контрактов |

Скрипт читает файлы чанками по 5 000 строк — безопасен для файлов размером >1 ГБ. При повторном запуске дубликаты пропускаются (upsert по `ste_id` / `contract_id`).

---

## Логика работы

### Поисковый пайплайн

```
Запрос пользователя
       │
       ▼
  [SymSpell]  ←─ словарь из названий СТЕ
  Исправление опечаток (расстояние ≤ 2, O(1))
       │
       ▼
  [SynonymExpander]  ←─ MANUAL dict + Word2Vec
  Расширение синонимами (USB → флэш-накопитель, …)
       │
       ▼
  [BM25 Index]  ←─ название × 3, категория × 1.5, атрибуты × 0.8
  Топ-200 кандидатов
       │
       ▼
  [LightGBM LambdaRank]  ←─ 10 фич: история закупок ИНН,
  Персонализированное        сезонность, Redis-сессия, популярность
  ранжирование → топ-N
       │
       ▼
  [DB filter]  ←─ фильтры цены / категории
  Финальная выдача
```

Если ML-сервис недоступен — автоматический fallback на ILIKE-поиск по PostgreSQL.

### Персонализация

- **Долгосрочная** (LightGBM): частота закупок товара за 30/90/365 дней, доля категории в закупках ИНН, среднее spend, дней с последней покупки.
- **Краткосрочная** (Redis-сессия): клик (+0.15), долгий просмотр (+0.25), покупка (+0.50), быстрый уход (−0.20). Применяется немедленно к следующему запросу.

### Автодополнение

При вводе в строку поиска появляется выпадающий список из 6 подсказок (debounce 150 мс). Подсказки учитывают историю запросов сессии, кликнутые товары и профиль ИНН. Пункт, помеченный «ИИ», — лучшая рекомендация модели.

---

## Структура проекта

```
app/
├── backend/                  # FastAPI-сервер (порт 8080)
│   ├── main.py               # Фабрика приложения, регистрация роутеров
│   ├── models.py             # SQLModel-таблицы: ste, contracts, user_events, search_logs
│   ├── database.py           # engine, get_db(), init_db()
│   ├── ml_client.py          # HTTP-клиент к ML-сервису, fallback при ошибках
│   ├── routes/
│   │   ├── pages.py          # HTML-страницы: /, /search, /card/{ste_id}
│   │   ├── search.py         # POST /api/search (JSON)
│   │   ├── events.py         # POST /api/event (поведенческие сигналы)
│   │   ├── ste.py            # GET /ste/{ste_id} (JSON)
│   │   └── suggest.py        # GET /suggest, GET /explain, GET /api/autocomplete
│   └── Dockerfile
│
├── frontend/                 # Шаблоны и статика
│   ├── templates/
│   │   ├── base.html         # Общий layout, header, подключение JS/CSS
│   │   ├── index.html        # Главная страница с рекомендациями
│   │   ├── search.html       # Страница результатов поиска
│   │   └── card.html         # Карточка товара
│   └── static/
│       ├── css/
│       │   ├── styles.css    # Основные стили
│       │   └── mobile.css    # Адаптивная вёрстка + стили автодополнения
│       └── js/
│           ├── events.js     # trackClick(), showToast()
│           └── autocomplete.js  # Выпадающий список подсказок
│
├── ml_service/               # ML-сервис (порт 8001)
│   ├── api/
│   │   └── main.py           # FastAPI: /search, /suggest, /event, /analogues, /metrics
│   ├── ml/
│   │   ├── search_index.py   # BM25Index, SpellChecker, SynonymExpander,
│   │   │                     # SearchEngine, QueryPredictor, PriceAnalogueIndex
│   │   └── ranker.py         # FeatureExtractor, Reranker (LightGBM), ExplainEngine
│   ├── config/
│   │   └── settings.py       # Пути к моделям, гиперпараметры, Redis-конфиг
│   └── Dockerfile
│
├── tenderhack/tenderhack/    # Исходные артефакты ML-модели
│   └── models/               # .pkl-файлы: bm25, lgbm, spell, synonyms, …
│
├── scripts/
│   └── load_data.py          # Загрузка СТЕ и контрактов из CSV в PostgreSQL
│
├── data/                     # CSV-файлы данных (не в git, >1 ГБ каждый)
└── docker-compose.yml
```

---

## Стек технологий

| Слой | Технологии |
|---|---|
| **Backend** | Python 3.11, FastAPI, SQLModel, SQLAlchemy, Jinja2 (SSR) |
| **ML** | LightGBM (LambdaRank), bm25s, symspellpy, pymorphy3, gensim (Word2Vec) |
| **База данных** | PostgreSQL 15 |
| **Кеш / сессии** | Redis 7 |
| **Frontend** | HTML + CSS (без фреймворков), ванильный JS |
| **Инфраструктура** | Docker, Docker Compose |
| **HTTP-клиент** | httpx (async) |

---

## Переменные окружения

| Переменная | Дефолт | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@db:5432/hackathon` | Строка подключения к PostgreSQL |
| `ML_SERVICE_URL` | `http://ml_service:8000` | Адрес ML-сервиса внутри Docker-сети |
| `REDIS_HOST` | `redis` | Хост Redis (для ML-сервиса) |
| `MODELS_DIR` | `/app/models` | Путь к директории с .pkl-файлами моделей |

---

## API (краткий справочник)

### Веб-страницы

| Метод | URL | Описание |
|---|---|---|
| GET | `/` | Главная: рекомендации, ИИ-подсказка |
| GET | `/search?q=&inn=` | Поиск с фильтрами и пагинацией |
| GET | `/card/{ste_id}?inn=` | Карточка товара с историей и аналогами |

### JSON API

| Метод | URL | Описание |
|---|---|---|
| POST | `/api/search` | Поиск (JSON-клиенты) |
| POST | `/api/event` | Поведенческое событие (click/dwell/bounce/purchase) |
| GET | `/api/autocomplete?q=&inn=` | Подсказки для строки поиска (топ-6) |
| GET | `/ste/{ste_id}` | Данные СТЕ (JSON) |
| GET | `/suggest?inn=` | ИИ-подсказка запроса по профилю ИНН |
| GET | `/explain?inn=&query=` | Объяснение персонализации |
| GET | `/health` | Статус сервисов |
