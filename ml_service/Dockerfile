FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.135.3 uvicorn==0.34.0 pydantic==2.12.5

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
