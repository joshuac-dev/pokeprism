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
    # Simulations can run for several hours.  The default Redis visibility
    # timeout (3600 s) causes the broker to redeliver the task before it is
    # acknowledged when acks_late=True.  Set a generous 24-hour window so
    # long-running tasks are never redelivered while still running.
    broker_transport_options={"visibility_timeout": 86400},
)

celery_app.conf.beat_schedule = {
    "nightly-hh-simulation": {
        "task": "pokeprism.run_scheduled_hh",
        "schedule": crontab(hour=2, minute=0),
    },
    "advance-simulation-queue": {
        "task": "pokeprism.advance_simulation_queue",
        "schedule": 60.0,  # every 60 seconds
    },
}

# Explicitly import task modules so Celery registers all tasks
celery_app.conf.imports = [
    "app.tasks.simulation",
    "app.tasks.scheduled",
]
