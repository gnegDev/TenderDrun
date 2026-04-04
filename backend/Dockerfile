FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.135.3 \
    uvicorn[standard]==0.34.0 \
    sqlmodel==0.0.22 \
    psycopg2-binary==2.9.10 \
    httpx==0.28.1 \
    pydantic==2.12.5 \
    pandas==2.2.3 \
    jinja2==3.1.6 \
    aiofiles==24.1.0 \
    python-multipart==0.0.22

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
