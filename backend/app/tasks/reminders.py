import datetime

from app.celery_app import celery_app


@celery_app.task
def notify_due_reminders():
    """Crea una notificación (una sola vez) por cada recordatorio que vence en las próximas 24 h."""
    from app.database import SessionLocal
    from app.models import Reminder
    from app.utils.notifications import create_notification

    db = SessionLocal()
    now = datetime.datetime.utcnow()
    try:
        due = (
            db.query(Reminder)
            .filter(
                Reminder.is_completed == False,  # noqa: E712
                Reminder.notified_at.is_(None),
                Reminder.due_date <= now + datetime.timedelta(hours=24),
            )
            .all()
        )
        for r in due:
            dog_name = r.match.dog.name if r.match and r.match.dog else "tu perrito"
            create_notification(
                db, user_id=r.user_id, type="reminder", title=f"Recordatorio: {r.title}",
                body=f"{r.title} de {dog_name} es el {r.due_date.strftime('%d/%m/%Y')}. ¡No lo olvides! 🐾",
                data={"reminder_id": r.id, "match_id": r.match_id}, commit=False,
            )
            r.notified_at = now
        db.commit()
        return {"notified": len(due)}
    finally:
        db.close()
