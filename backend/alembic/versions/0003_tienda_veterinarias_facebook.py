"""Tienda con Mercado Pago Marketplace (split, envíos, devoluciones, facturas y CFDI de la plataforma),
directorio de veterinarias con reseñas, y lectura de grupos públicos de Facebook por estado.

Idempotente a propósito (IF NOT EXISTS / IF EXISTS), igual que 0002: las bases de desarrollo ya recibieron
estas tablas con create_all y estas columnas con ALTER ... IF NOT EXISTS mientras se construían las
funciones. Los nombres de restricciones e índices son los que PostgreSQL y SQLAlchemy ya asignaron ahí
(p. ej. orders_refuge_id_fkey, veterinaries_owner_user_id_key), así que en una base vacía y en una base
de desarrollo queda exactamente el mismo esquema y `alembic check` no encuentra diferencias.

Datos: los pedidos anteriores reciben refuge_id (del refugio de sus productos; todos los pedidos tenían
productos de un solo refugio) y subtotal = total (no cobraban envío aparte).

Revision ID: 0003_tienda_vets_facebook
Revises: 0002_produccion
Create Date: 2026-10-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_tienda_vets_facebook'
down_revision = '0002_produccion'
branch_labels = None
depends_on = None


def _has_foreign_key(table: str, name: str) -> bool:
    return any(fk.get("name") == name for fk in sa.inspect(op.get_bind()).get_foreign_keys(table))


def upgrade() -> None:
    # --- Veterinarias --------------------------------------------------------------------------
    # La dirección del consultorio es pública (es un negocio): coordenadas exactas. De Google solo se
    # guarda el place_id; reseñas y calificación se piden en vivo (políticas de Places).
    op.create_table('veterinaries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('state', sa.String(length=100), nullable=True),
    sa.Column('postal_code', sa.String(length=10), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('whatsapp', sa.String(length=50), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('website', sa.String(length=500), nullable=True),
    sa.Column('hours', sa.JSON(), nullable=False),
    sa.Column('services', sa.JSON(), nullable=False),
    sa.Column('emergency_24h', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('photos', sa.JSON(), nullable=False),
    sa.Column('responsible_vet_name', sa.String(length=255), nullable=False),
    sa.Column('cedula_profesional', sa.String(length=20), nullable=False),
    sa.Column('cedula_institution', sa.String(length=255), nullable=True),
    sa.Column('cedula_document_id', sa.String(length=64), nullable=True),
    sa.Column('google_place_id', sa.String(length=255), nullable=True),
    sa.Column('google_maps_url', sa.String(length=500), nullable=True),
    sa.Column('google_place_checked_at', sa.DateTime(), nullable=True),
    sa.Column('google_place_error_at', sa.DateTime(), nullable=True),
    sa.Column('google_fetched_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('rejection_note', sa.Text(), nullable=True),
    sa.Column('is_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('verified_by_id', sa.Integer(), nullable=True),
    sa.Column('verification_expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['verified_by_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_user_id'),
    if_not_exists=True,
    )
    op.create_index('idx_veterinaries_city', 'veterinaries', ['city'], unique=False, if_not_exists=True)
    op.create_index('idx_veterinaries_geo', 'veterinaries', ['latitude', 'longitude'], unique=False, if_not_exists=True)
    op.create_index('idx_veterinaries_status', 'veterinaries', ['status'], unique=False, if_not_exists=True)
    op.create_index('ix_veterinaries_created_at', 'veterinaries', ['created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_veterinaries_id', 'veterinaries', ['id'], unique=False, if_not_exists=True)
    # Evidencia del cotejo (carrera y captura fechada del RNP, privada), retención de 12 meses desde que deja de
    # publicarse y consentimiento de publicación del responsable (gap-veterinarias-y-resenas 03, 15 y 16)
    op.add_column('veterinaries', sa.Column('cedula_carrera', sa.String(length=255), nullable=True), if_not_exists=True)
    op.add_column('veterinaries', sa.Column('verification_evidence_document_id', sa.String(length=64), nullable=True),
                  if_not_exists=True)
    op.add_column('veterinaries', sa.Column('unpublished_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('veterinaries', sa.Column('consent_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('veterinaries', sa.Column('consent_terms_version', sa.String(length=20), nullable=True), if_not_exists=True)

    # Reseñas propias de la app (una por usuario y clínica)
    op.create_table('veterinary_reviews',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('veterinary_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('visited_month', sa.String(length=7), nullable=True),
    sa.Column('incentivized', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('owner_reply', sa.Text(), nullable=True),
    sa.Column('owner_reply_at', sa.DateTime(), nullable=True),
    sa.Column('is_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['veterinary_id'], ['veterinaries.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('veterinary_id', 'user_id', name='uq_veterinary_reviews_vet_user'),
    if_not_exists=True,
    )
    op.create_index('idx_veterinary_reviews_vet_created', 'veterinary_reviews', ['veterinary_id', 'created_at'],
                    unique=False, if_not_exists=True)
    op.create_index('ix_veterinary_reviews_id', 'veterinary_reviews', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_veterinary_reviews_user_id', 'veterinary_reviews', ['user_id'], unique=False, if_not_exists=True)
    # Aclaración publicada sin comentarios junto a la reseña
    op.add_column('veterinary_reviews', sa.Column('clarification', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('veterinary_reviews', sa.Column('clarification_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # Solicitudes de aclaración y quejas (también de personas sin cuenta)
    op.create_table('veterinary_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('veterinary_id', sa.Integer(), nullable=False),
    sa.Column('review_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('relation', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=False),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('resolved_by_id', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['review_id'], ['veterinary_reviews.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['veterinary_id'], ['veterinaries.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index('idx_veterinary_requests_status_created', 'veterinary_requests', ['status', 'created_at'],
                    unique=False, if_not_exists=True)
    op.create_index('idx_veterinary_requests_vet', 'veterinary_requests', ['veterinary_id'], unique=False,
                    if_not_exists=True)
    op.create_index('ix_veterinary_requests_id', 'veterinary_requests', ['id'], unique=False, if_not_exists=True)

    # --- Tienda: cuentas de Mercado Pago de los refugios (OAuth; tokens cifrados con una llave derivada
    # de SECRET_KEY), perfil fiscal, solicitudes de factura y CFDI mensuales de la plataforma ----------
    op.create_table('refuge_payment_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=30), server_default=sa.text("'mercadopago'"), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'connected'"), nullable=False),
    sa.Column('mp_user_id', sa.String(length=50), nullable=True),
    sa.Column('access_token_enc', sa.Text(), nullable=True),
    sa.Column('refresh_token_enc', sa.Text(), nullable=True),
    sa.Column('public_key', sa.String(length=255), nullable=True),
    sa.Column('scope', sa.String(length=255), nullable=True),
    sa.Column('live_mode', sa.Boolean(), nullable=True),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('connected_at', sa.DateTime(), nullable=True),
    sa.Column('refreshed_at', sa.DateTime(), nullable=True),
    sa.Column('disconnected_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('refuge_id'),
    if_not_exists=True,
    )
    op.create_index('ix_refuge_payment_accounts_id', 'refuge_payment_accounts', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_refuge_payment_accounts_mp_user_id', 'refuge_payment_accounts', ['mp_user_id'],
                    unique=False, if_not_exists=True)

    op.create_table('refuge_fiscal_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=False),
    sa.Column('person_type', sa.String(length=10), nullable=False),
    sa.Column('rfc', sa.String(length=13), nullable=False),
    sa.Column('legal_name', sa.String(length=255), nullable=False),
    sa.Column('regimen_fiscal', sa.String(length=3), nullable=False),
    sa.Column('postal_code', sa.String(length=5), nullable=False),
    sa.Column('is_donataria', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('csf_document_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('refuge_id'),
    if_not_exists=True,
    )
    op.create_index('ix_refuge_fiscal_profiles_id', 'refuge_fiscal_profiles', ['id'], unique=False, if_not_exists=True)

    # Factura de la compra (Modelo B: la emite el refugio vendedor; aquí se guardan la solicitud y los archivos)
    op.create_table('order_invoices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'requested'"), nullable=False),
    sa.Column('rfc', sa.String(length=13), nullable=False),
    sa.Column('legal_name', sa.String(length=255), nullable=False),
    sa.Column('regimen_fiscal', sa.String(length=3), nullable=False),
    sa.Column('postal_code', sa.String(length=5), nullable=False),
    sa.Column('uso_cfdi', sa.String(length=4), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('uuid', sa.String(length=36), nullable=True),
    sa.Column('xml_document_id', sa.String(length=64), nullable=True),
    sa.Column('pdf_document_id', sa.String(length=64), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('requested_at', sa.DateTime(), nullable=False),
    sa.Column('issued_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('order_id'),
    if_not_exists=True,
    )
    op.create_index('ix_order_invoices_id', 'order_invoices', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_order_invoices_refuge_status', 'order_invoices', ['refuge_id', 'status'], unique=False, if_not_exists=True)
    op.create_index('ix_order_invoices_user_id', 'order_invoices', ['user_id'], unique=False, if_not_exists=True)
    # Un CFDI (UUID) no se adjunta a dos pedidos (en PostgreSQL los NULL no chocan entre sí)
    op.create_index('uq_order_invoices_uuid', 'order_invoices', ['uuid'], unique=True, if_not_exists=True)

    # CFDI de la plataforma por refugio y mes: comisión (ingreso) y retenciones (personas físicas)
    op.create_table('cfdis',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('period', sa.String(length=7), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'pending_pac'"), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('iva', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('isr_retenido', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('iva_retenido', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('total', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('xml_document_id', sa.String(length=64), nullable=True),
    sa.Column('pdf_document_id', sa.String(length=64), nullable=True),
    sa.Column('provider_ref', sa.String(length=100), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('issued_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'period', 'refuge_id', name='uq_cfdis_kind_period_refuge'),
    if_not_exists=True,
    )
    op.create_index('ix_cfdis_id', 'cfdis', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_cfdis_refuge_id', 'cfdis', ['refuge_id'], unique=False, if_not_exists=True)
    op.create_index('ix_cfdis_status_period', 'cfdis', ['status', 'period'], unique=False, if_not_exists=True)

    # Reembolsos totales y parciales de cada pedido, en el mes en que ocurren (estados de cuenta y CFDI)
    op.create_table('order_refunds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.Integer(), nullable=False),
    sa.Column('refuge_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('fee_reversed', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('isr_reversed', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('iva_reversed', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('is_full', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('provider_refund_id', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=True),
    sa.Column('by', sa.String(length=20), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ),
    sa.ForeignKeyConstraint(['refuge_id'], ['refuges.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index('ix_order_refunds_id', 'order_refunds', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_order_refunds_order_id', 'order_refunds', ['order_id'], unique=False, if_not_exists=True)
    op.create_index('ix_order_refunds_refuge_created', 'order_refunds', ['refuge_id', 'created_at'], unique=False,
                    if_not_exists=True)

    # --- Tienda: columnas nuevas -----------------------------------------------------------------
    # Envío por producto (0 = envío gratis; si no es nacional, ships_states lista los estados)
    op.add_column('products', sa.Column('shipping_cost', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('products', sa.Column('ships_nationwide', sa.Boolean(), server_default=sa.text('true'), nullable=False), if_not_exists=True)
    op.add_column('products', sa.Column('ships_states', sa.JSON(), nullable=True), if_not_exists=True)
    op.add_column('products', sa.Column('handling_days', sa.Integer(), server_default=sa.text('3'), nullable=False), if_not_exists=True)

    # Pedido: refugio vendedor, montos del split, dirección estructurada, historial, devolución y reembolso
    op.add_column('orders', sa.Column('refuge_id', sa.Integer(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('subtotal', sa.Numeric(precision=10, scale=2), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_total', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('orders', sa.Column('fee_percent', sa.Numeric(precision=5, scale=2), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('fee_amount', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('orders', sa.Column('isr_retenido', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('orders', sa.Column('iva_retenido', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('orders', sa.Column('net_amount', sa.Numeric(precision=10, scale=2), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('payment_mode', sa.String(length=20), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('collector_id', sa.String(length=50), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_name', sa.String(length=255), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_phone', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_street', sa.String(length=255), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_ext_number', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_int_number', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_neighborhood', sa.String(length=255), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_city', sa.String(length=120), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_state', sa.String(length=100), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_postal_code', sa.String(length=10), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipping_references', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('tracking_url', sa.String(length=500), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('timeline', sa.JSON(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('preparing_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('completed_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('cancelled_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('cancel_reason', sa.String(length=50), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('return_reason', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('return_details', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('return_photos', sa.JSON(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('return_requested_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('return_decided_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('return_decision_note', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('refund_id', sa.String(length=100), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('refund_amount', sa.Numeric(precision=10, scale=2), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('refund_status', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('refunded_at', sa.DateTime(), nullable=True), if_not_exists=True)
    # Cancelación con causa registrada, aviso de despacho vencido y link de pago pendiente
    op.add_column('orders', sa.Column('cancel_note', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('dispatch_warned_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('checkout_url', sa.String(length=500), nullable=True), if_not_exists=True)
    # Evidencia de la aceptación de las condiciones de compra (consumidor-ecommerce-05 y 06)
    op.add_column('orders', sa.Column('terms_version', sa.String(length=20), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('terms_hash', sa.String(length=64), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('terms_accepted_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('consent_prepayment_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('terms_ip', sa.String(length=45), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('terms_user_agent', sa.String(length=255), nullable=True), if_not_exists=True)
    if not _has_foreign_key('orders', 'orders_refuge_id_fkey'):
        op.create_foreign_key('orders_refuge_id_fkey', 'orders', 'refuges', ['refuge_id'], ['id'])
    op.create_index('ix_orders_refuge_id', 'orders', ['refuge_id'], unique=False, if_not_exists=True)
    op.create_index('ix_orders_refuge_paid_at', 'orders', ['refuge_id', 'paid_at'], unique=False, if_not_exists=True)

    # Pedidos anteriores: refugio vendedor (desde sus productos) y subtotal (no tenían envío aparte)
    op.execute("""
        UPDATE orders o SET refuge_id = s.refuge_id
        FROM (SELECT oi.order_id, MIN(p.refuge_id) AS refuge_id
              FROM order_items oi JOIN products p ON p.id = oi.product_id
              GROUP BY oi.order_id) s
        WHERE o.id = s.order_id AND o.refuge_id IS NULL
    """)
    op.execute("UPDATE orders SET subtotal = total WHERE subtotal IS NULL")
    # Reembolsos hechos antes de order_refunds: una fila por pedido con la parte proporcional de comisión
    # y retenciones (Mercado Pago reparte el reembolso en proporción entre refugio y plataforma)
    op.execute("""
        INSERT INTO order_refunds (order_id, refuge_id, amount, fee_reversed, isr_reversed, iva_reversed, is_full,
                                   provider_refund_id, status, by, note, created_at)
        SELECT o.id, o.refuge_id, o.refund_amount,
               CASE WHEN o.total > 0 THEN round(o.fee_amount * o.refund_amount / o.total, 2) ELSE 0 END,
               CASE WHEN o.total > 0 THEN round(o.isr_retenido * o.refund_amount / o.total, 2) ELSE 0 END,
               CASE WHEN o.total > 0 THEN round(o.iva_retenido * o.refund_amount / o.total, 2) ELSE 0 END,
               (o.refund_amount >= COALESCE(o.paid_amount, o.total) OR o.status IN ('refunded', 'cancelled')),
               o.refund_id, o.refund_status, 'system', 'Reembolso registrado antes del historial de reembolsos.',
               COALESCE(o.refunded_at, o.cancelled_at, o.created_at)
        FROM orders o
        WHERE o.refund_amount IS NOT NULL AND o.refund_amount > 0
          AND NOT EXISTS (SELECT 1 FROM order_refunds r WHERE r.order_id = o.id)
    """)

    # Donativos: modo de cobro (split o cuenta de la plataforma) y comisión
    op.add_column('donations', sa.Column('payment_mode', sa.String(length=20), nullable=True), if_not_exists=True)
    op.add_column('donations', sa.Column('collector_id', sa.String(length=50), nullable=True), if_not_exists=True)
    op.add_column('donations', sa.Column('fee_percent', sa.Numeric(precision=5, scale=2), nullable=True), if_not_exists=True)
    op.add_column('donations', sa.Column('fee_amount', sa.Numeric(precision=10, scale=2), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('donations', sa.Column('net_amount', sa.Numeric(precision=10, scale=2), nullable=True), if_not_exists=True)
    op.add_column('donations', sa.Column('approved_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # --- Grupos públicos de Facebook (kind "group") y estado de los reportes ------------------------
    op.add_column('facebook_groups', sa.Column('state', sa.String(length=100), nullable=True), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('group_url', sa.String(length=500), nullable=True), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('provider', sa.String(length=30), nullable=True), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('provider_ref', sa.String(length=255), nullable=True), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('last_fetched_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('last_post_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('posts_fetched_total', sa.Integer(), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('reports_created_total', sa.Integer(), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('cost_estimate_total', sa.Numeric(precision=10, scale=4), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    op.add_column('facebook_groups', sa.Column('last_error', sa.Text(), nullable=True), if_not_exists=True)
    op.create_index('ix_facebook_groups_state', 'facebook_groups', ['state'], unique=False, if_not_exists=True)
    op.add_column('lost_reports', sa.Column('state', sa.String(length=100), nullable=True), if_not_exists=True)
    op.create_index('ix_lost_reports_state', 'lost_reports', ['state'], unique=False, if_not_exists=True)
    # Intervalo entre lecturas (cuenta también los intentos con error) separado de la marca de la última
    # lectura correcta, desde la que se piden las publicaciones siguientes
    op.add_column('facebook_groups', sa.Column('last_attempt_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # Contenido importado: fecha de la publicación original (caducidad), aceptación del voluntario y purga
    op.add_column('lost_reports', sa.Column('external_posted_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('lost_reports', sa.Column('consent_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('lost_reports', sa.Column('consent_version', sa.String(length=20), nullable=True), if_not_exists=True)
    op.add_column('lost_reports', sa.Column('purged_at', sa.DateTime(), nullable=True), if_not_exists=True)
    # Una publicación = un reporte. Antes del índice único se quitan los enlaces repetidos (se conserva el
    # reporte más antiguo con el enlace; los demás siguen publicados, sin external_url).
    op.execute("""
        UPDATE lost_reports l SET external_url = NULL
        WHERE l.external_url IS NOT NULL
          AND EXISTS (SELECT 1 FROM lost_reports o WHERE o.external_url = l.external_url AND o.id < l.id)
    """)
    op.create_index('uq_lost_reports_external_url', 'lost_reports', ['external_url'], unique=True,
                    postgresql_where=sa.text('external_url IS NOT NULL'), if_not_exists=True)
    op.drop_index('idx_lost_reports_external', table_name='lost_reports', if_exists=True)
    # Solicitudes de retiro sin cuenta (autor de una publicación importada)
    op.alter_column('content_reports', 'reporter_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Contenido importado y retiros sin cuenta
    op.execute("DELETE FROM content_reports WHERE reporter_id IS NULL")
    op.alter_column('content_reports', 'reporter_id', existing_type=sa.Integer(), nullable=False)
    op.create_index('idx_lost_reports_external', 'lost_reports', ['external_url'], unique=False, if_not_exists=True)
    op.drop_index('uq_lost_reports_external_url', table_name='lost_reports', if_exists=True)
    for column in ('purged_at', 'consent_version', 'consent_at', 'external_posted_at'):
        op.drop_column('lost_reports', column, if_exists=True)
    op.drop_column('facebook_groups', 'last_attempt_at', if_exists=True)

    # Grupos de Facebook y estado de reportes
    op.drop_index('ix_lost_reports_state', table_name='lost_reports', if_exists=True)
    op.drop_column('lost_reports', 'state', if_exists=True)
    op.drop_index('ix_facebook_groups_state', table_name='facebook_groups', if_exists=True)
    for column in ('last_error', 'cost_estimate_total', 'reports_created_total', 'posts_fetched_total',
                   'last_post_at', 'last_fetched_at', 'provider_ref', 'provider', 'group_url', 'state'):
        op.drop_column('facebook_groups', column, if_exists=True)

    # Donativos
    for column in ('approved_at', 'net_amount', 'fee_amount', 'fee_percent', 'collector_id', 'payment_mode'):
        op.drop_column('donations', column, if_exists=True)

    # Tablas que dependen de orders / refuges / veterinaries (primero las dependientes)
    op.drop_table('order_refunds', if_exists=True)
    op.drop_table('order_invoices', if_exists=True)
    op.drop_table('cfdis', if_exists=True)
    op.drop_table('refuge_fiscal_profiles', if_exists=True)
    op.drop_table('refuge_payment_accounts', if_exists=True)
    op.drop_table('veterinary_requests', if_exists=True)
    op.drop_table('veterinary_reviews', if_exists=True)
    op.drop_table('veterinaries', if_exists=True)

    # Pedidos
    op.drop_index('ix_orders_refuge_paid_at', table_name='orders', if_exists=True)
    op.drop_index('ix_orders_refuge_id', table_name='orders', if_exists=True)
    if _has_foreign_key('orders', 'orders_refuge_id_fkey'):
        op.drop_constraint('orders_refuge_id_fkey', 'orders', type_='foreignkey')
    for column in ('terms_user_agent', 'terms_ip', 'consent_prepayment_at', 'terms_accepted_at', 'terms_hash',
                   'terms_version', 'checkout_url', 'dispatch_warned_at', 'cancel_note',
                   'refunded_at', 'refund_status', 'refund_amount', 'refund_id', 'return_decision_note',
                   'return_decided_at', 'return_requested_at', 'return_photos', 'return_details', 'return_reason',
                   'cancel_reason', 'cancelled_at', 'completed_at', 'preparing_at', 'timeline', 'tracking_url',
                   'shipping_references', 'shipping_postal_code', 'shipping_state', 'shipping_city',
                   'shipping_neighborhood', 'shipping_int_number', 'shipping_ext_number', 'shipping_street',
                   'shipping_phone', 'shipping_name', 'collector_id', 'payment_mode', 'net_amount', 'iva_retenido',
                   'isr_retenido', 'fee_amount', 'fee_percent', 'shipping_total', 'subtotal', 'refuge_id'):
        op.drop_column('orders', column, if_exists=True)

    # Productos
    for column in ('handling_days', 'ships_states', 'ships_nationwide', 'shipping_cost'):
        op.drop_column('products', column, if_exists=True)
