from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.observability import init_sentry, setup_logging

setup_logging()
init_sentry("celery")

redis_url = settings.redis_url or "redis://localhost:6379/0"

celery_app = Celery(
    "patitasfind",
    broker=redis_url,
    backend=redis_url,
    include=[
        "app.tasks.whatsapp",
        "app.tasks.facebook",
        "app.tasks.images",
        "app.tasks.matching",
        "app.tasks.reminders",
        "app.tasks.payments",
    ],
)

beat_schedule = {
    "reminders-daily": {
        "task": "app.tasks.reminders.notify_due_reminders",
        "schedule": crontab(hour=14, minute=0),  # 8:00 en Ciudad de México (UTC-6)
    },
    "photo-signature-backfill": {
        "task": "app.tasks.images.backfill_photo_signatures",
        "schedule": crontab(minute=15),  # cada hora
    },
}
if settings.facebook_page_access_token:
    beat_schedule["facebook-pages-hourly"] = {
        "task": "app.tasks.facebook.scrape_facebook_groups",
        "schedule": crontab(minute=0),
    }

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "app.tasks.whatsapp.*": {"queue": "whatsapp"},
        "app.tasks.facebook.*": {"queue": "facebook"},
    },
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule=beat_schedule,
)
