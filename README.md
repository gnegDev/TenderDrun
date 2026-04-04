# TenderDrun — персонализированный поиск СТЕ

## Запуск

```bash
docker compose up --build
```

После старта:
- Backend API: http://localhost:8080
- ML-сервис (заглушка): http://localhost:8001
- Документация API: http://localhost:8080/docs

## Загрузка данных

База создаётся автоматически при старте backend. Для загрузки CSV-файлов:

```bash
# Убедитесь, что БД запущена (docker compose up db)
python scripts/load_data.py \
  --ste "data/СТЕ_20260403.csv" \
  --contracts "data/Контракты_20260403.csv"
```

Скрипт работает чанками по 5 000 строк — безопасен для файлов >1 ГБ.

Переопределить адрес БД:
```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/hackathon \
  python scripts/load_data.py --ste data/...
```

## Эндпоинты

### POST /search
Поиск СТЕ с персонализацией по ИНН.

```bash
curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d '{"query": "кабель медный", "inn": "7701234567"}'
```

Ответ:
```json
{
  "results": [
    {"ste_id": "123", "name": "Кабель ВВГ 3х2.5", "category": "Кабели", "score": 0.95, "reason": "..."}
  ],
  "suggested_query": "кабель ВВГ"
}
```

### POST /event
Запись поведенческого события.

```bash
curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -d '{"inn": "7701234567", "query": "кабель", "ste_id": "123", "position": 1, "event_type": "click"}'
```

Типы событий: `click`, `dwell`, `quick_return`, `target_action`, `impression_skip`

### GET /ste/{ste_id}
Полные данные о товарной позиции.

```bash
curl http://localhost:8080/ste/123
```

### GET /suggest?inn={inn}
Подсказка поискового запроса на основе истории пользователя.

```bash
curl "http://localhost:8080/suggest?inn=7701234567"
```

### GET /explain?inn={inn}&query={query}
Объяснение персонализации — последние 20 событий пользователя.

```bash
curl "http://localhost:8080/explain?inn=7701234567&query=кабель"
```

### GET /health
Проверка работоспособности сервиса.

## Структура проекта

```
app/
├── backend/
│   ├── main.py          # FastAPI-приложение, подключение роутеров
│   ├── database.py      # Подключение к PostgreSQL, init_db
│   ├── models.py        # SQLModel-таблицы: SteItem, Contract, UserEvent, SearchLog
│   ├── ml_client.py     # HTTP-клиент к ML-сервису с fallback на БД
│   ├── routes/
│   │   ├── search.py    # POST /search
│   │   ├── events.py    # POST /event
│   │   ├── ste.py       # GET /ste/{ste_id}
│   │   └── suggest.py   # GET /suggest, GET /explain
│   └── Dockerfile
├── ml_service/
│   ├── main.py          # Заглушка ML-сервиса
│   └── Dockerfile
├── scripts/
│   └── load_data.py     # Загрузка CSV в БД
├── data/                # CSV-файлы (не в git)
└── docker-compose.yml
```

## Переменные окружения

| Переменная | Дефолт | Описание |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@db:5432/hackathon` | Адрес PostgreSQL |
| `ML_SERVICE_URL` | `http://ml_service:8001` | Адрес ML-сервиса |
