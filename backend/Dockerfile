FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY --chown=app:app . .

# Pre-create the ptcgl_logs directory with app ownership so named volumes
# initialised from this image layer get the right permissions on first mount.
RUN mkdir -p /data/ptcgl_logs && chown -R app:app /data/ptcgl_logs

USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
