from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=5, default_retry_delay=30)
def process_mercadopago_payment(self, payment_id: str, ref_hint: str | None = None, mp_user_id: str | None = None):
    """ref_hint ("order-12") y mp_user_id (vendedor) solo ayudan a elegir el token del refugio en split."""
    from app.database import SessionLocal
    from app.services.payment_flow import process_payment

    db = SessionLocal()
    try:
        return process_payment(db, payment_id, ref_hint=ref_hint, mp_user_id=mp_user_id)
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task
def expire_pending_payments():
    """Cada 15 min (beat): cancela pedidos/expira donaciones sin pagar y devuelve el inventario apartado."""
    from app.database import SessionLocal
    from app.services.payment_flow import expire_pending_payments as run

    db = SessionLocal()
    try:
        return run(db)
    finally:
        db.close()


@celery_app.task
def auto_complete_orders():
    """Diaria (beat): pedidos entregados hace más de ORDER_AUTO_COMPLETE_DAYS sin devolución => "completed"."""
    from app.database import SessionLocal
    from app.services.order_flow import auto_complete_orders as run

    db = SessionLocal()
    try:
        return run(db)
    finally:
        db.close()


@celery_app.task
def refresh_seller_tokens():
    """Semanal (beat): renueva los tokens OAuth de Mercado Pago de los refugios que vencen en menos de 30 días."""
    from app.database import SessionLocal
    from app.services.mercadopago_oauth import refresh_expiring_accounts

    db = SessionLocal()
    try:
        return refresh_expiring_accounts(db)
    finally:
        db.close()


@celery_app.task
def enforce_dispatch_deadlines():
    """Diaria (beat): pedidos pagados sin enviar. Avisa al vencer el plazo de despacho y, al vencer
    ORDER_DISPATCH_GRACE_DAYS hábiles más, los cancela con reembolso total (consumidor-ecommerce-13)."""
    from app.database import SessionLocal
    from app.services.order_flow import enforce_dispatch_deadlines as run

    db = SessionLocal()
    try:
        return run(db)
    finally:
        db.close()
