"""Celery application factory and Beat schedule configuration."""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "pokeprism",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "nightly-hh-simulation": {
        "task": "pokeprism.run_scheduled_hh",
        "schedule": crontab(hour=2, minute=0),
    },
}

# Auto-discover tasks from the tasks package
celery_app.autodiscover_tasks(["app.tasks"])
