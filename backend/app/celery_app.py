from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

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
        "app.tasks.facebook_groups",
        "app.tasks.images",
        "app.tasks.matching",
        "app.tasks.reminders",
        "app.tasks.payments",
        "app.tasks.invoicing",
        "app.tasks.notifications",
        "app.tasks.reports",
        "app.tasks.veterinaries",
        "app.tasks.reglas",
        "app.tasks.retention",
        "app.tasks.moderacion_legal",
        "app.tasks.solicitudes",
        "app.tasks.legal_docs",
    ],
)

beat_schedule = {
    # Reglas de negocio (services/reglas.py): meta de 24 h para las facturas y seguimiento diario
    "rules-invoice-requests-hourly": {
        "task": "app.tasks.reglas.remind_invoice_requests",
        "schedule": crontab(minute=25),  # cada hora
    },
    "rules-daily": {
        "task": "app.tasks.reglas.run_daily_rules",
        "schedule": crontab(hour=15, minute=40),  # 9:40 en Ciudad de México (avisos en horario hábil)
    },
    "reminders-daily": {
        "task": "app.tasks.reminders.notify_due_reminders",
        "schedule": crontab(hour=14, minute=0),  # 8:00 en Ciudad de México (UTC-6)
    },
    "photo-signature-backfill": {
        "task": "app.tasks.images.backfill_photo_signatures",
        "schedule": crontab(minute=15),  # cada hora
    },
    "uploads-orphan-cleanup": {
        "task": "app.tasks.images.cleanup_orphan_uploads",
        "schedule": crontab(hour=9, minute=30),  # 3:30 en Ciudad de México
    },
    "payments-expire-pending": {
        "task": "app.tasks.payments.expire_pending_payments",
        "schedule": crontab(minute="*/15"),  # libera el inventario de pedidos sin pagar
    },
    "lost-reports-expire-daily": {
        "task": "app.tasks.reports.expire_stale_reports",
        "schedule": crontab(hour=10, minute=0),  # 4:00 en Ciudad de México
    },
    "orders-auto-complete-daily": {
        "task": "app.tasks.payments.auto_complete_orders",
        "schedule": crontab(hour=10, minute=10),  # 4:10 en Ciudad de México
    },
    "orders-dispatch-deadline-daily": {
        "task": "app.tasks.payments.enforce_dispatch_deadlines",
        "schedule": crontab(hour=15, minute=30),  # 9:30 en Ciudad de México: avisos y cancelaciones por falta de envío
    },
    "mercadopago-seller-tokens-weekly": {
        "task": "app.tasks.payments.refresh_seller_tokens",
        "schedule": crontab(day_of_week=2, hour=11, minute=30),  # martes 5:30: tokens OAuth que vencen en 30 días
    },
    "cfdi-monthly": {
        "task": "app.tasks.invoicing.issue_monthly_cfdi",
        "schedule": crontab(day_of_month=3, hour=15, minute=0),  # día 3, 9:00 en Ciudad de México (mes anterior)
    },
    "veterinaries-google-weekly": {
        "task": "app.tasks.veterinaries.refresh_google_places",
        "schedule": crontab(day_of_week=1, hour=11, minute=0),  # lunes 5:00 en Ciudad de México
    },
    "veterinaries-verification-expiry-daily": {
        "task": "app.tasks.veterinaries.expire_verifications",
        "schedule": crontab(hour=10, minute=20),  # 4:20 en Ciudad de México
    },
    "veterinaries-documents-retention-daily": {
        "task": "app.tasks.veterinaries.purge_documents",
        "schedule": crontab(hour=10, minute=40),  # 4:40 en Ciudad de México
    },
    # Aviso previo (30 días) de versiones nuevas de documentos legales que no se haya mandado al sincronizar
    "legal-change-notices-daily": {
        "task": "app.tasks.legal_docs.send_pending_notices",
        "schedule": crontab(hour=16, minute=0),  # 10:00 en Ciudad de México
    },
    "retention-purge-daily": {
        "task": "app.tasks.retention.run_retention",
        "schedule": crontab(hour=11, minute=5),  # 5:05 en Ciudad de México: tabla de conservación (services/retention.py)
    },
    # Moderación legal (la purga de la bóveda de evidencia la hace retention-purge-daily con evidence.purge_expired)
    "copyright-restore-daily": {
        "task": "app.tasks.moderacion_legal.restore_counter_noticed_content",
        "schedule": crontab(hour=10, minute=50),  # 4:50 en Ciudad de México: contra-avisos en su día hábil 10
    },
    "moderation-suspensions-hourly": {
        "task": "app.tasks.moderacion_legal.lift_expired_suspensions",
        "schedule": crontab(minute=25),  # suspensiones temporales que ya terminaron
    },
    "moderation-overdue-daily": {
        "task": "app.tasks.moderacion_legal.alert_overdue_moderation",
        "schedule": crontab(hour=15, minute=0),  # 9:00 en Ciudad de México: plazos vencidos
    },
    # Centro de solicitudes (services/solicitudes.py)
    "compliance-requests-daily": {
        "task": "app.tasks.solicitudes.daily_maintenance",
        "schedule": crontab(hour=14, minute=30),  # 8:30 en Ciudad de México: identificaciones, cierres y plazos
    },
    "imported-removals-hourly": {
        "task": "app.tasks.solicitudes.enforce_imported_removals",
        "schedule": crontab(minute=35),  # retiro de publicaciones importadas en menos de 72 h
    },
    # «Soy el autor» (POST /facebook/author-removal): mismo plazo que los retiros del centro de solicitudes
    "imported-author-removals-hourly": {
        "task": "app.tasks.facebook_groups.purge_author_removals",
        "schedule": crontab(minute=45),
    },
}
if settings.facebook_page_access_token:
    beat_schedule["facebook-pages-hourly"] = {
        "task": "app.tasks.facebook.scrape_facebook_groups",
        "schedule": crontab(minute=0),
    }
# Grupos públicos de Facebook: se leen por zona al crear reportes; aquí solo se expiran los importados viejos
beat_schedule["facebook-groups-expire-daily"] = {
    "task": "app.tasks.facebook_groups.expire_imported_posts",
    "schedule": crontab(hour=10, minute=40),  # 4:40 en Ciudad de México
}

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Una tarea solo se confirma al terminar: si el worker muere a la mitad, otra la retoma
    # (las tareas deben ser idempotentes). El visibility_timeout de Redis (1 h) es mayor que el límite.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=300,  # SoftTimeLimitExceeded: la tarea puede limpiar y reintentar
    task_time_limit=600,  # después de esto el proceso hijo se mata
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,  # recicla procesos (fugas de memoria de Pillow / IA)
    task_default_queue="default",
    task_routes={
        "app.tasks.whatsapp.*": {"queue": "whatsapp"},
        "app.tasks.facebook.*": {"queue": "facebook"},
        "app.tasks.facebook_groups.*": {"queue": "facebook"},
    },
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    beat_schedule=beat_schedule,
)


@worker_process_init.connect
def _reset_db_pool(**_):
    """Cada hijo del worker (prefork) abre sus propias conexiones; las heredadas del padre no se comparten."""
    from app.database import engine

    engine.dispose(close=False)
