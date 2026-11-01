"""Preparación para producción: moderación, bitácora de administración, pagos idempotentes,
alertas cercanas, verificación de correo, revocación de sesiones, pedidos con envío e índices.

Idempotente a propósito (IF NOT EXISTS / IF EXISTS): las bases creadas antes con create_all +
STARTUP_MIGRATIONS (desarrollo y cualquier producción previa) ya tienen parte de estas columnas,
tablas e índices. app/migrate.py las marca como 0001_baseline y luego aplica esta revisión, que
solo crea lo que falte. Los nombres de índice son los mismos que ya existen en esas bases.

Revision ID: 0002_produccion
Revises: 0001_baseline
Create Date: 2026-10-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002_produccion'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def _is_nullable(table: str, column: str) -> bool | None:
    """None si la columna no existe."""
    for col in sa.inspect(op.get_bind()).get_columns(table):
        if col["name"] == column:
            return bool(col["nullable"])
    return None


def upgrade() -> None:
    # --- Tablas nuevas -------------------------------------------------------------------------
    # Pagos de Mercado Pago ya aplicados (un pago se acredita una sola vez)
    op.create_table('payment_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('payment_id', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('object_id', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.String(length=50), nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=10), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'payment_id', 'status', name='uq_payment_events_payment_status'),
    if_not_exists=True,
    )
    op.create_index('ix_payment_events_id', 'payment_events', ['id'], unique=False, if_not_exists=True)

    # Bitácora de acciones de administración
    op.create_table('admin_audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('target_type', sa.String(length=50), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index('ix_admin_audit_logs_actor_id', 'admin_audit_logs', ['actor_id'], unique=False, if_not_exists=True)
    op.create_index('ix_admin_audit_logs_created_at', 'admin_audit_logs', ['created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_admin_audit_logs_id', 'admin_audit_logs', ['id'], unique=False, if_not_exists=True)

    # Reportes de contenido (moderación)
    op.create_table('content_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reporter_id', sa.Integer(), nullable=False),
    sa.Column('target_type', sa.String(length=30), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=40), nullable=False),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'open'"), nullable=False),
    sa.Column('action', sa.String(length=30), nullable=True),
    sa.Column('admin_notes', sa.Text(), nullable=True),
    sa.Column('resolved_by', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['reporter_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    if_not_exists=True,
    )
    op.create_index('ix_content_reports_id', 'content_reports', ['id'], unique=False, if_not_exists=True)
    op.create_index('ix_content_reports_reporter_created', 'content_reports', ['reporter_id', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_content_reports_status_created', 'content_reports', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_content_reports_target', 'content_reports', ['target_type', 'target_id'], unique=False, if_not_exists=True)

    # --- Columnas nuevas (las NOT NULL llevan server_default para las filas existentes) ---------
    # usuarios: alertas cercanas, suspensión por moderación, verificación de correo, revocación de sesiones
    op.add_column('users', sa.Column('notify_nearby', sa.Boolean(), server_default=sa.text('true'), nullable=False), if_not_exists=True)
    op.add_column('users', sa.Column('suspended_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default=sa.text('0'), nullable=False), if_not_exists=True)
    # contenido oculto por moderación
    op.add_column('dogs', sa.Column('is_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('lost_reports', sa.Column('is_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('products', sa.Column('is_hidden', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    # reportes: último cambio y última acción de quien reporta (reloj de la expiración a los 90 días;
    # las filas existentes parten de su último cambio conocido)
    op.add_column('lost_reports', sa.Column('updated_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('lost_reports', sa.Column('last_activity_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.execute("UPDATE lost_reports SET last_activity_at = COALESCE(updated_at, created_at) WHERE last_activity_at IS NULL")
    # pedidos: revisión de pagos y envío
    op.add_column('orders', sa.Column('paid_amount', sa.Numeric(precision=10, scale=2), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('review_note', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('carrier', sa.String(length=100), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('tracking_number', sa.String(length=100), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('shipped_at', sa.DateTime(), nullable=True), if_not_exists=True)
    op.add_column('orders', sa.Column('delivered_at', sa.DateTime(), nullable=True), if_not_exists=True)
    # donaciones: revisión de pagos; share_name y opted_out_at faltaban en la baseline (STARTUP_MIGRATIONS las agregaba)
    op.add_column('donations', sa.Column('paid_amount', sa.Numeric(precision=10, scale=2), nullable=True), if_not_exists=True)
    op.add_column('donations', sa.Column('review_note', sa.Text(), nullable=True), if_not_exists=True)
    op.add_column('donations', sa.Column('share_name', sa.Boolean(), server_default=sa.text('false'), nullable=False), if_not_exists=True)
    op.add_column('bot_interactions', sa.Column('opted_out_at', sa.DateTime(), nullable=True), if_not_exists=True)

    # Bases antiguas: STARTUP_MIGRATIONS creó report_type como NULL DEFAULT 'lost'; el modelo es NOT NULL
    if _is_nullable('lost_reports', 'report_type'):
        op.execute("UPDATE lost_reports SET report_type = 'lost' WHERE report_type IS NULL")
        op.alter_column('lost_reports', 'report_type', existing_type=sa.String(length=50), nullable=False)

    # --- Índices (mismos nombres que STARTUP_MIGRATIONS / las bases existentes) --------------------
    op.create_index('idx_users_email', 'users', ['email'], unique=False, if_not_exists=True)
    op.create_index('ix_users_nearby_geo', 'users', ['latitude', 'longitude'], unique=False,
                    postgresql_where=sa.text('notify_nearby AND is_active AND latitude IS NOT NULL'), if_not_exists=True)
    op.create_index('idx_dogs_city', 'dogs', ['city'], unique=False, if_not_exists=True)
    op.create_index('idx_dogs_geo', 'dogs', ['latitude', 'longitude'], unique=False, if_not_exists=True)
    op.create_index('idx_dogs_owner', 'dogs', ['owner_id'], unique=False, if_not_exists=True)
    op.create_index('idx_dogs_status', 'dogs', ['status'], unique=False, if_not_exists=True)
    op.create_index('idx_dogs_status_created', 'dogs', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_dogs_created_at', 'dogs', ['created_at'], unique=False, if_not_exists=True)
    op.create_index('idx_lost_reports_external', 'lost_reports', ['external_url'], unique=False, if_not_exists=True)
    op.create_index('idx_lost_reports_geo', 'lost_reports', ['latitude', 'longitude'], unique=False, if_not_exists=True)
    op.create_index('idx_lost_reports_status', 'lost_reports', ['status'], unique=False, if_not_exists=True)
    op.create_index('idx_lost_reports_status_created', 'lost_reports', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_lost_reports_created_at', 'lost_reports', ['created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_lost_reports_reporter_id', 'lost_reports', ['reporter_id'], unique=False, if_not_exists=True)
    op.create_index('idx_matches_dog', 'matches', ['dog_id'], unique=False, if_not_exists=True)
    op.create_index('idx_matches_status', 'matches', ['status'], unique=False, if_not_exists=True)
    op.create_index('idx_matches_user', 'matches', ['user_id'], unique=False, if_not_exists=True)
    op.create_index('ix_adoption_applications_match_id', 'adoption_applications', ['match_id'], unique=False, if_not_exists=True)
    op.create_index('idx_conversations_users', 'conversations', ['user_a_id', 'user_b_id'], unique=False, if_not_exists=True)
    op.create_index('ix_conversations_lost_report_id', 'conversations', ['lost_report_id'], unique=False, if_not_exists=True)
    op.create_index('ix_conversations_match_id', 'conversations', ['match_id'], unique=False, if_not_exists=True)
    op.create_index('idx_messages_conv', 'messages', ['conversation_id', 'id'], unique=False, if_not_exists=True)
    op.create_index('idx_messages_unread', 'messages', ['conversation_id', 'sender_id'], unique=False,
                    postgresql_where=sa.text('NOT is_read'), if_not_exists=True)
    op.create_index('idx_notifications_user_read', 'notifications', ['user_id', 'is_read'], unique=False, if_not_exists=True)
    op.create_index('idx_refuges_status', 'refuges', ['status'], unique=False, if_not_exists=True)
    op.create_index('idx_foster_homes_status', 'foster_homes', ['status'], unique=False, if_not_exists=True)
    op.create_index('ix_products_refuge_id', 'products', ['refuge_id'], unique=False, if_not_exists=True)
    op.create_index('ix_orders_status_created_at', 'orders', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_orders_user_id', 'orders', ['user_id'], unique=False, if_not_exists=True)
    op.create_index('ix_order_items_order_id', 'order_items', ['order_id'], unique=False, if_not_exists=True)
    op.create_index('ix_order_items_product_id', 'order_items', ['product_id'], unique=False, if_not_exists=True)
    op.create_index('ix_donations_status_created_at', 'donations', ['status', 'created_at'], unique=False, if_not_exists=True)
    op.create_index('ix_reminders_match_id', 'reminders', ['match_id'], unique=False, if_not_exists=True)


def downgrade() -> None:
    # Índices
    op.drop_index('ix_reminders_match_id', table_name='reminders', if_exists=True)
    op.drop_index('ix_donations_status_created_at', table_name='donations', if_exists=True)
    op.drop_index('ix_order_items_product_id', table_name='order_items', if_exists=True)
    op.drop_index('ix_order_items_order_id', table_name='order_items', if_exists=True)
    op.drop_index('ix_orders_user_id', table_name='orders', if_exists=True)
    op.drop_index('ix_orders_status_created_at', table_name='orders', if_exists=True)
    op.drop_index('ix_products_refuge_id', table_name='products', if_exists=True)
    op.drop_index('idx_foster_homes_status', table_name='foster_homes', if_exists=True)
    op.drop_index('idx_refuges_status', table_name='refuges', if_exists=True)
    op.drop_index('idx_notifications_user_read', table_name='notifications', if_exists=True)
    op.drop_index('idx_messages_unread', table_name='messages', postgresql_where=sa.text('NOT is_read'), if_exists=True)
    op.drop_index('idx_messages_conv', table_name='messages', if_exists=True)
    op.drop_index('ix_conversations_match_id', table_name='conversations', if_exists=True)
    op.drop_index('ix_conversations_lost_report_id', table_name='conversations', if_exists=True)
    op.drop_index('idx_conversations_users', table_name='conversations', if_exists=True)
    op.drop_index('ix_adoption_applications_match_id', table_name='adoption_applications', if_exists=True)
    op.drop_index('idx_matches_user', table_name='matches', if_exists=True)
    op.drop_index('idx_matches_status', table_name='matches', if_exists=True)
    op.drop_index('idx_matches_dog', table_name='matches', if_exists=True)
    op.drop_index('ix_lost_reports_reporter_id', table_name='lost_reports', if_exists=True)
    op.drop_index('ix_lost_reports_created_at', table_name='lost_reports', if_exists=True)
    op.drop_index('idx_lost_reports_status_created', table_name='lost_reports', if_exists=True)
    op.drop_index('idx_lost_reports_status', table_name='lost_reports', if_exists=True)
    op.drop_index('idx_lost_reports_geo', table_name='lost_reports', if_exists=True)
    op.drop_index('idx_lost_reports_external', table_name='lost_reports', if_exists=True)
    op.drop_index('ix_dogs_created_at', table_name='dogs', if_exists=True)
    op.drop_index('idx_dogs_status_created', table_name='dogs', if_exists=True)
    op.drop_index('idx_dogs_status', table_name='dogs', if_exists=True)
    op.drop_index('idx_dogs_owner', table_name='dogs', if_exists=True)
    op.drop_index('idx_dogs_geo', table_name='dogs', if_exists=True)
    op.drop_index('idx_dogs_city', table_name='dogs', if_exists=True)
    op.drop_index('ix_users_nearby_geo', table_name='users',
                  postgresql_where=sa.text('notify_nearby AND is_active AND latitude IS NOT NULL'), if_exists=True)
    op.drop_index('idx_users_email', table_name='users', if_exists=True)

    # Columnas
    op.drop_column('bot_interactions', 'opted_out_at', if_exists=True)
    op.drop_column('donations', 'share_name', if_exists=True)
    op.drop_column('donations', 'review_note', if_exists=True)
    op.drop_column('donations', 'paid_amount', if_exists=True)
    op.drop_column('orders', 'delivered_at', if_exists=True)
    op.drop_column('orders', 'shipped_at', if_exists=True)
    op.drop_column('orders', 'tracking_number', if_exists=True)
    op.drop_column('orders', 'carrier', if_exists=True)
    op.drop_column('orders', 'review_note', if_exists=True)
    op.drop_column('orders', 'paid_amount', if_exists=True)
    op.drop_column('lost_reports', 'last_activity_at', if_exists=True)
    op.drop_column('lost_reports', 'updated_at', if_exists=True)
    op.drop_column('products', 'is_hidden', if_exists=True)
    op.drop_column('lost_reports', 'is_hidden', if_exists=True)
    op.drop_column('dogs', 'is_hidden', if_exists=True)
    op.drop_column('users', 'token_version', if_exists=True)
    op.drop_column('users', 'email_verified_at', if_exists=True)
    op.drop_column('users', 'email_verified', if_exists=True)
    op.drop_column('users', 'suspended_at', if_exists=True)
    op.drop_column('users', 'notify_nearby', if_exists=True)

    # Tablas
    op.drop_index('ix_content_reports_target', table_name='content_reports', if_exists=True)
    op.drop_index('ix_content_reports_status_created', table_name='content_reports', if_exists=True)
    op.drop_index('ix_content_reports_reporter_created', table_name='content_reports', if_exists=True)
    op.drop_index('ix_content_reports_id', table_name='content_reports', if_exists=True)
    op.drop_table('content_reports', if_exists=True)
    op.drop_index('ix_admin_audit_logs_id', table_name='admin_audit_logs', if_exists=True)
    op.drop_index('ix_admin_audit_logs_created_at', table_name='admin_audit_logs', if_exists=True)
    op.drop_index('ix_admin_audit_logs_actor_id', table_name='admin_audit_logs', if_exists=True)
    op.drop_table('admin_audit_logs', if_exists=True)
    op.drop_index('ix_payment_events_id', table_name='payment_events', if_exists=True)
    op.drop_table('payment_events', if_exists=True)
