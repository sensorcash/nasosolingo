# Образ приложения Насосолинго для продакшена.
FROM python:3.11-slim

# Не писать .pyc, не буферизовать логи
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Системные зависимости для psycopg2 (миграции) и сборки колёс
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Сначала зависимости — кэшируется, пока requirements не менялись
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код
COPY . .

# Непривилегированный пользователь
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Проверка живости для оркестратора
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Прод-запуск без --reload; воркеры под нагрузку добавишь флагом --workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
