"""Tabla de conservación de datos: fuente única de los plazos (contrato K-CONSERV).

La misma lista alimenta:
- la purga diaria (app.tasks.retention.run_retention -> run_purge), que borra o anonimiza lo que venció, y
- GET /cumplimiento/conservacion, la tabla en vivo de conservacion.html («es la que vale»).

Cada categoría dice cómo se aplica (`aplicacion`):
  automatica    la borra o anonimiza una tarea programada (esta purga u otra que se indica en `tarea`)
  caduca_sola   vence sola (sesiones, códigos, cachés con vencimiento)
  al_eliminar   se borra al eliminar la cuenta o al cambiar el dato
  bloqueo       se conserva bloqueada por obligación legal; la supresión al vencer es un procedimiento interno
  procedimiento la aplica el equipo con un procedimiento documentado (no hay tarea automática)
  proveedor     la aplica el proveedor (Meta, PostHog, Sentry) según su contrato
  navegador     vive en el navegador de la persona
  no_se_guarda  no se almacena

Plazos tomados de docs/legal/requisitos.json (retention R01-R48). Si cambias un plazo aquí cambia en la purga y
en la página a la vez. Mientras haya un incidente abierto con freeze_purges, o RETENTION_PURGE_ENABLED=false,
la purga no borra nada (runbook-incidentes.md §5 paso 2 y §11.1). El congelamiento dura como máximo
FREEZE_MAX_DIAS (30) desde que se activó o se renovó (lo renueva un superadmin), y no detiene el borrado de las
identificaciones y documentos de verificación (FREEZE_EXEMPT) salvo que el incidente los incluya en sus sistemas
o categorías de datos afectados.
"""
import datetime
import ipaddress
import logging
import os
import re
from pathlib import Path

from sqlalchemy import JSON, String, Text, and_, cast, func, or_
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

VERSION = "2026-10-17"
BATCH = 1000

# --------------------------------------------------------------------------- plazos (días)
DOCUMENTOS_VERIFICACION_DIAS = 30  # R15/R17: imagen de INE, acta o cédula tras aprobar o rechazar
DOCUMENTOS_ABANDONADOS_DIAS = 7  # documento privado subido y nunca usado en un formulario
CSF_SIN_OPERACIONES_DIAS = 30  # constancia fiscal de un Refugio cerrado que nunca operó
EXPEDIENTE_FISCAL_DIAS = 3650  # R09: 10 años desde la última operación
CHATS_CUENTA_ELIMINADA_DIAS = 90  # R21
CHATS_CON_REPORTE_DIAS = 365  # R21: con reporte, hasta resolverlo más 12 meses
REPORTES_ANONIMIZAR_DIAS = 90  # R23: tras resolverse o caducar
BOT_DIAS = 365  # R27
MODERACION_DIAS = 730  # R32: 24 meses
MODERACION_MENORES_DIAS = 3650  # R32: 10 años si involucra a menores o a una autoridad
INCUMPLIMIENTOS_DIAS = 2190  # R41: 72 meses
BITACORA_ADMIN_DIAS = 1825  # R36: 5 años
INCIDENTES_DIAS = 1825  # R35: 5 años tras el cierre
REGISTROS_TECNICOS_DIAS = 90  # R37
IP_RECORTE_DIAS = 30  # R37: IP acortada a los 30 días
NOTIFICACIONES_DIAS = 365
CUESTIONARIOS_DIAS = 365  # R19
AUTORIZACION_VOLUNTARIOS_DIAS = 730  # R26: 2 años tras el retiro
CUENTA_MINIMOS_DIAS = 365  # R02: 1 año sin compras ni donativos
CUENTA_MINIMOS_CON_OPERACIONES_DIAS = 3650  # R02: 10 años con compras o donativos
ENVIO_ANONIMIZAR_EXTRA_DIAS = 365  # R06: garantía (reclamación) + 1 año
REGISTRO_PURGAS_DIAS = 1825  # evidencia de cumplimiento (R35)
SANCIONADAS_DIAS = 730  # R42: 24 meses de correo/teléfono de una cuenta cancelada para impedir el re-registro
FREEZE_MAX_DIAS = 30  # congelamiento de purgas por un incidente: máximo 30 días por vez (lo renueva un superadmin)
# Purgas que siguen corriendo durante un congelamiento, salvo que el incidente incluya esos documentos
FREEZE_EXEMPT = ("documentos_verificacion", "documentos_abandonados")
FREEZE_DOC_HINTS = ("private", "document", "identific", "cedula", "cédula", "verificacion", "verificación")
FREEZE_DOC_WORDS = {"ine", "acta", "actas"}
EVIDENCIA_DIAS_NATURALES = 135  # R30: 90 días hábiles (135 naturales de margen)


def _orphan_photo_hours() -> int:
    try:
        from app.tasks.images import ORPHAN_MIN_AGE_HOURS

        return int(ORPHAN_MIN_AGE_HOURS)
    except Exception:  # noqa: BLE001
        return 48


def _vet_constants() -> tuple[int, int]:
    try:
        from app.tasks import veterinaries as vt

        return int(vt.DOCUMENT_RETENTION_DAYS), int(vt.REQUEST_RETENTION_DAYS)
    except Exception:  # noqa: BLE001
        return 365, 730


def _days_text(days: int) -> str:
    if days % 365 == 0 and days >= 365:
        years = days // 365
        return "1 año" if years == 1 else f"{years} años"
    if days % 30 == 0 and days >= 60:
        return f"{days // 30} meses"
    return "1 día" if days == 1 else f"{days} días"


def _minutes_text(minutes: int) -> str:
    if minutes % 1440 == 0:
        return _days_text(minutes // 1440)
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hora" if hours == 1 else f"{hours} horas"
    return f"{minutes} minutos"


# --------------------------------------------------------------------------- la tabla
def categories() -> list[dict]:
    """La tabla de conservación vigente (se arma con la configuración actual)."""
    vet_docs_days, vet_requests_days = _vet_constants()
    local_backups = int(os.environ.get("BACKUP_RETENTION_DAYS") or 14)
    offsite_backups = int(os.environ.get("BACKUP_OFFSITE_RETENTION_DAYS") or 30)
    fb_days = settings.fb_groups_post_ttl_days
    rows = [
        # ---------------------------------------------------------------- cuenta
        dict(clave="cuenta_activa", ref="R01", categoria="Cuenta y perfil activos",
             plazo="Mientras la cuenta exista", desde="—",
             accion="Al eliminar la cuenta se borran o anonimizan los datos (fila siguiente)",
             fundamento="LFPDPPP arts. 10 y 12", aplicacion="al_eliminar"),
        dict(clave="cuenta_eliminada", ref="R02",
             categoria="Cuenta eliminada: nombre, correo, teléfono, foto, ubicación y contraseña",
             plazo="Se anonimizan en el momento en que eliminas tu cuenta", desde="Eliminación de la cuenta",
             accion="Anonimización inmediata", fundamento="LFPDPPP arts. 24 y 25", aplicacion="al_eliminar",
             tarea="DELETE /users/me"),
        dict(clave="cuenta_eliminada_minimos", ref="R02",
             categoria="Cuenta eliminada: mínimos bloqueados (id, fechas y versiones aceptadas)",
             plazo=f"{_days_text(CUENTA_MINIMOS_CON_OPERACIONES_DIAS)} si hubo compra o donativo; si no, "
                   f"{_days_text(CUENTA_MINIMOS_DIAS)}",
             desde="Eliminación de la cuenta", accion="Supresión de los datos residuales del perfil",
             fundamento="LFPDPPP arts. 24 y 25 fr. I a III; CCom art. 1047; LFPC art. 14", aplicacion="automatica",
             dias=CUENTA_MINIMOS_DIAS),
        dict(clave="sesiones", categoria="Sesiones iniciadas en la app",
             plazo=f"{_minutes_text(settings.access_token_expire_minutes)}; personal administrador "
                   f"{_minutes_text(settings.admin_token_expire_minutes)}",
             desde="Inicio de sesión", accion="Vencen solas; puedes cerrarlas antes en todos tus dispositivos",
             fundamento="LFPDPPP arts. 11 y 18", aplicacion="caduca_sola"),
        dict(clave="codigos_verificacion", categoria="Códigos de verificación por SMS",
             plazo=f"{_minutes_text(settings.otp_ttl_minutes)}", desde="Envío del código",
             accion="Vencen solos; se guarda solo una huella (hash), nunca el código", fundamento="LFPDPPP art. 18",
             aplicacion="caduca_sola"),
        dict(clave="mfa_admin", categoria="Verificación en dos pasos del personal administrador (secreto cifrado y "
                                          "códigos de recuperación)",
             plazo="Mientras la persona tenga acceso al panel", desde="—",
             accion="Se borran al quitar el acceso o eliminar la cuenta", fundamento="LFPDPPP art. 18",
             aplicacion="al_eliminar"),
        # ---------------------------------------------------------------- legal y dinero
        dict(clave="aceptaciones", ref="R03",
             categoria="Bitácora de aceptaciones y consentimientos (Términos, Aviso, 18+, compra, convenios, WhatsApp)",
             plazo="10 años", desde="La aceptación o el fin de la relación, lo que ocurra después",
             accion="Bloqueo (registro de solo inserción); supresión al vencer",
             fundamento="CCom arts. 49 y 1047; LFPC art. 76 Bis 1 fr. IV; CCF art. 640", aplicacion="bloqueo"),
        dict(clave="versiones_legales", ref="R04", categoria="Versiones publicadas de documentos legales (con SHA-256)",
             plazo="Permanente en el historial", desde="Fin de vigencia de la versión", accion="Archivo",
             fundamento="CCom art. 49 párr. 2; NOM-151-SCFI-2016", aplicacion="bloqueo"),
        dict(clave="pedidos", ref="R05",
             categoria="Pedidos, comprobantes, aceptación de condiciones, reclamaciones, revocaciones y reembolsos",
             plazo="10 años", desde="Fecha de la operación", accion="Bloqueo con datos mínimos; supresión al vencer",
             fundamento="CCom arts. 38 y 49; LFPC arts. 13, 14 y 55; CFF art. 30", aplicacion="bloqueo"),
        dict(clave="envio_comprador", ref="R06", categoria="Domicilio y teléfono de envío del comprador",
             plazo=f"Se anonimizan {_days_text(settings.return_claim_window_days + ENVIO_ANONIMIZAR_EXTRA_DIAS)} "
                   "después de la entrega (plazo de reclamación más 1 año)",
             desde="Entrega (o cancelación del pedido)",
             accion="Anonimización de calle, números, colonia, referencias y teléfono; quedan ciudad, estado y CP",
             fundamento="LFPC arts. 14, 76 Bis fr. I y 93; LFPDPPP art. 12", aplicacion="automatica",
             dias=settings.return_claim_window_days + ENVIO_ANONIMIZAR_EXTRA_DIAS),
        dict(clave="fiscal_comprador", ref="R07",
             categoria="CFDI, contabilidad y datos fiscales del comprador que pidió factura (cifrados)",
             plazo="5 años desde la declaración relacionada y no menos que el pedido (10 años)",
             desde="Fecha de la operación", accion="Bloqueo; fuera del borrado ARCO mientras corre el plazo",
             fundamento="CFF art. 30; CCom art. 38", aplicacion="bloqueo"),
        dict(clave="expediente_fiscal_refugio", ref="R09",
             categoria="Expediente fiscal del Refugio vendedor o receptor de fondos (RFC cifrado y Constancia de "
                       "Situación Fiscal cifrada)",
             plazo=f"{_days_text(EXPEDIENTE_FISCAL_DIAS)} desde la última operación; si el Refugio cerró sin "
                   f"operaciones, {_days_text(CSF_SIN_OPERACIONES_DIAS)}",
             desde="Última operación (o cierre del Refugio)", accion="Borrado seguro de la constancia",
             fundamento="CFF art. 30; LFPIORPI art. 18 fr. IV", aplicacion="automatica", dias=EXPEDIENTE_FISCAL_DIAS),
        dict(clave="pagos", ref="R10",
             categoria="Registro de pagos, comisiones, contracargos y conciliaciones de Mercado Pago",
             plazo="10 años", desde="Cada operación", accion="Bloqueo",
             fundamento="CFF art. 30; CCom arts. 38, 49 y 298", aplicacion="bloqueo"),
        dict(clave="donativos", ref="R11", categoria="Donativos (folio, ID de pago, monto, Refugio, comisiones, neto)",
             plazo="10 años", desde="Fecha del donativo", accion="Bloqueo sin uso operativo; supresión al vencer",
             fundamento="CFF art. 30; CCom arts. 38 y 49", aplicacion="bloqueo"),
        dict(clave="bonificaciones", categoria="Bonificaciones del 20 % por productos defectuosos o que no "
                                                "correspondían (monto, referencia de pago y evidencia)",
             plazo="10 años", desde="Fecha del pedido", accion="Bloqueo sin uso operativo; supresión al vencer",
             fundamento="LFPC arts. 92 Ter y 98; CCom art. 49", aplicacion="bloqueo"),
        dict(clave="alertas_donativos", categoria="Alertas de donativos acumulados por persona y Refugio (umbrales "
                                                  "de identificación y aviso) y su revisión",
             plazo="10 años", desde="Fecha de la alerta", accion="Bloqueo sin uso operativo; supresión al vencer",
             fundamento="LFPIORPI art. 18 fr. IV", aplicacion="bloqueo"),
        dict(clave="oauth_mercadopago", ref="R13", categoria="Credenciales OAuth de Refugios en Mercado Pago (cifradas)",
             plazo="Mientras la vinculación esté activa", desde="Desvinculación o revocación",
             accion="Borrado inmediato", fundamento="Términos de Mercado Pago para Desarrolladores; LFPDPPP art. 18",
             aplicacion="automatica", tarea="mercadopago_oauth.disconnect"),
        dict(clave="tarjeta", ref="R45", categoria="Datos de tarjeta", plazo="Nunca los recibimos ni guardamos",
             desde="—", accion="—", fundamento="PCI DSS (contractual)", aplicacion="no_se_guarda"),
        # ---------------------------------------------------------------- verificación
        dict(clave="documentos_verificacion", ref="R15/R17",
             categoria="Imágenes de identificaciones, actas y cédulas usadas para verificar (cifradas)",
             plazo=f"{_days_text(DOCUMENTOS_VERIFICACION_DIAS)} después de aprobar o rechazar",
             desde="Decisión de verificación", accion="Borrado seguro de la imagen; queda solo la constancia",
             fundamento="LFPDPPP arts. 8, 10, 12 y 18", aplicacion="automatica", dias=DOCUMENTOS_VERIFICACION_DIAS),
        dict(clave="documentos_abandonados", categoria="Documentos privados subidos que nunca se enviaron",
             plazo=_days_text(DOCUMENTOS_ABANDONADOS_DIAS), desde="Subida", accion="Borrado seguro",
             fundamento="LFPDPPP art. 12", aplicacion="automatica", dias=DOCUMENTOS_ABANDONADOS_DIAS),
        dict(clave="constancias_clinicas", ref="R16",
             categoria="Captura del cotejo de la cédula en el Registro Nacional de Profesionistas (Clínicas)",
             plazo=f"{_days_text(vet_docs_days)} después de dejar de publicarse",
             desde="Rechazo, revocación, vencimiento o baja", accion="Borrado seguro",
             fundamento="LFPDPPP art. 12; CCF art. 1910", aplicacion="automatica", dias=vet_docs_days,
             tarea="app.tasks.veterinaries.purge_documents"),
        dict(clave="solicitudes_clinicas", categoria="Aclaraciones y quejas sobre Clínicas y reseñas (resueltas)",
             plazo=_days_text(vet_requests_days), desde="Resolución", accion="Supresión",
             fundamento="Ley de Responsabilidad Civil CDMX art. 38", aplicacion="automatica", dias=vet_requests_days,
             tarea="app.tasks.veterinaries.purge_documents"),
        # ---------------------------------------------------------------- uso de la plataforma
        dict(clave="cuestionarios_adopcion", ref="R19", categoria="Respuestas de los cuestionarios de adopción",
             plazo=f"{_days_text(CUESTIONARIOS_DIAS)} desde la postulación, una vez cerrada", desde="Postulación",
             accion="Supresión de las respuestas", fundamento="LFPDPPP arts. 10, 12 y 35", aplicacion="automatica",
             dias=CUESTIONARIOS_DIAS),
        dict(clave="chats_cuentas_eliminadas", ref="R21", categoria="Chats de una cuenta eliminada",
             plazo=f"{_days_text(CHATS_CUENTA_ELIMINADA_DIAS)} tras eliminar la cuenta; con reporte, hasta "
                   f"resolverlo más {_days_text(CHATS_CON_REPORTE_DIAS)}; con retención legal, lo que dure",
             desde="Eliminación de la cuenta o resolución del reporte", accion="Supresión de los mensajes",
             fundamento="LFPDPPP arts. 10, 12 y 25 fr. III", aplicacion="automatica", dias=CHATS_CUENTA_ELIMINADA_DIAS),
        dict(clave="ubicacion", ref="R22", categoria="Ubicación guardada para alertas",
             plazo="Hasta que la cambies o la borres, o elimines la cuenta", desde="—", accion="Supresión inmediata",
             fundamento="LFPDPPP art. 12", aplicacion="al_eliminar"),
        dict(clave="reportes_expiracion", ref="R23", categoria="Reportes de perdidos y encontrados sin actividad",
             plazo=f"Expiran a los {settings.report_expiry_days} días sin cambios (los puedes renovar)",
             desde="Última actividad", accion="Dejan de mostrarse", fundamento="LFPDPPP arts. 9 fr. III y 10",
             aplicacion="automatica", dias=settings.report_expiry_days, tarea="app.tasks.reports.expire_stale_reports"),
        dict(clave="reportes_anonimizar", ref="R23",
             categoria="Reportes de perdidos y encontrados resueltos, caducados o cerrados",
             plazo=f"{_days_text(REPORTES_ANONIMIZAR_DIAS)} después de resolverse o caducar",
             desde="Resolución o caducidad",
             accion="Anonimización: se borran fotos, descripción, teléfono y ubicación; quedan ciudad, fecha y resultado",
             fundamento="LFPDPPP arts. 9 fr. III y 10", aplicacion="automatica", dias=REPORTES_ANONIMIZAR_DIAS),
        dict(clave="importados_facebook", ref="R25",
             categoria="Reportes importados de grupos de Facebook y envíos de voluntarios (foto, texto depurado, enlace)",
             plazo=f"{_days_text(fb_days)} con borrado real (antes si el autor lo pide)", desde="Publicación original",
             accion="Borrado de fotos y texto; queda solo el registro de existencia y de retiros",
             fundamento="LFPDPPP arts. 10, 12 y 17; Meta Platform Terms 3.d", aplicacion="automatica", dias=fb_days,
             tarea="app.tasks.facebook_groups.expire_imported_posts"),
        dict(clave="autorizacion_voluntarios", ref="R26", categoria="Prueba de autorización del autor en envíos de voluntarios",
             plazo=f"Mientras esté publicado y {_days_text(AUTORIZACION_VOLUNTARIOS_DIAS)} después",
             desde="Retiro de la publicación", accion="Supresión", fundamento="Ley de Responsabilidad Civil CDMX art. 38",
             aplicacion="automatica", dias=AUTORIZACION_VOLUNTARIOS_DIAS),
        dict(clave="bot_whatsapp", ref="R27", categoria="Interacciones con el bot de WhatsApp",
             plazo=f"{_days_text(BOT_DIAS)} desde la última interacción (antes si lo pides)", desde="Última interacción",
             accion="Supresión; de los números dados de baja solo queda la baja", fundamento="Meta Platform Terms 3.d; "
             "LFPDPPP arts. 10 y 24", aplicacion="automatica", dias=BOT_DIAS),
        dict(clave="meta_cloud", ref="R28", categoria="Mensajes procesados por Meta (WhatsApp Cloud API)",
             plazo="Hasta 30 días en Meta", desde="Recepción", accion="Los borra Meta",
             fundamento="Documentación de Meta Cloud API (contractual)", aplicacion="proveedor"),
        dict(clave="cache_ia", ref="R29", categoria="Caché del análisis de fotos con IA",
             plazo="30 días, sin identificadores de la persona usuaria", desde="Análisis", accion="Vence sola",
             fundamento="LFPDPPP arts. 9 fr. III y 12", aplicacion="caduca_sola"),
        dict(clave="notificaciones", categoria="Avisos dentro de la app", plazo=_days_text(NOTIFICACIONES_DIAS),
             desde="Envío del aviso", accion="Supresión", fundamento="LFPDPPP art. 12", aplicacion="automatica",
             dias=NOTIFICACIONES_DIAS),
        dict(clave="fotos_abandonadas", categoria="Fotos subidas que no se usaron (formularios abandonados)",
             plazo=f"{_orphan_photo_hours()} horas", desde="Subida", accion="Borrado", fundamento="LFPDPPP art. 12",
             aplicacion="automatica", tarea="app.tasks.images.cleanup_orphan_uploads"),
        dict(clave="resenas_clinicas", ref="R43", categoria="Reseñas de Clínicas escritas en GuauWoow",
             plazo="Mientras exista la cuenta o hasta que su autor la borre", desde="Publicación",
             accion="Se borran al eliminar la cuenta", fundamento="LFPDPPP arts. 24 y 26", aplicacion="al_eliminar"),
        dict(clave="google_places", ref="R44", categoria="Contenido de Google Places (reseñas, calificación, autores)",
             plazo="No se almacena; solo el identificador del lugar", desde="—", accion="—",
             fundamento="Google Maps Platform ToS 3.2.3 (contractual)", aplicacion="no_se_guarda"),
        # ---------------------------------------------------------------- moderación y seguridad
        dict(clave="boveda_evidencia", ref="R30", categoria="Evidencia cifrada de cuentas y contenidos retirados",
             plazo=f"Al menos 90 días hábiles ({EVIDENCIA_DIAS_NATURALES} naturales); más con retención legal, "
                   "apelación u orden de conservación",
             desde="Retiro", accion="Borrado con registro", fundamento="Decreto NNA art. 5 fr. II; LFPA art. 28; "
             "LFPDPPP art. 25 fr. II y III; CNPP art. 303", aplicacion="automatica", dias=EVIDENCIA_DIAS_NATURALES),
        dict(clave="csam", ref="R31", categoria="Material de abuso sexual infantil detectado",
             plazo="Solo el original, aislado y con acceso bloqueado, hasta recibir instrucciones de la autoridad",
             desde="Detección", accion="Según instrucción de la autoridad (nunca se borra solo)",
             fundamento="Decreto NNA art. 5 fr. II y III; CNPP art. 222", aplicacion="bloqueo"),
        dict(clave="moderacion", ref="R32",
             categoria="Reportes de moderación y sus decisiones",
             plazo=f"{_days_text(MODERACION_DIAS)}; {_days_text(MODERACION_MENORES_DIAS)} si involucra a menores",
             desde="Resolución", accion="Anonimización (sin datos de quien reportó ni notas)",
             fundamento="Ley de Responsabilidad Civil CDMX art. 38; LFPC art. 14", aplicacion="automatica",
             dias=MODERACION_DIAS),
        dict(clave="incumplimientos", ref="R41", categoria="Medidas por incumplimientos (sanciones, fraude)",
             plazo="Máximo 72 meses", desde="Fecha de la medida", accion="Se desliga de la persona y se borran las notas",
             fundamento="LFPDPPP art. 10, último párrafo", aplicacion="automatica", dias=INCUMPLIMIENTOS_DIAS),
        dict(clave="derechos_autor", ref="R33", categoria="Expedientes de derechos de autor y hashes de bloqueo",
             plazo="10 años los expedientes; hashes mientras opere el servicio", desde="Cierre del procedimiento",
             accion="Supresión", fundamento="LFDA arts. 114 Octies y 232 Quinquies", aplicacion="bloqueo"),
        dict(clave="autoridades", ref="R34", categoria="Requerimientos de autoridades y denuncias presentadas",
             plazo="10 años", desde="Respuesta", accion="Supresión", fundamento="CCom art. 1047 por analogía",
             aplicacion="bloqueo"),
        dict(clave="expedientes_arco", ref="R35", categoria="Solicitudes ARCO, quejas y su seguimiento",
             plazo="5 años", desde="Cierre de la solicitud", accion="Supresión",
             fundamento="LFPA art. 79; LFPDPPP arts. 13 y 18", aplicacion="bloqueo"),
        dict(clave="incidentes", ref="R35", categoria="Registro de incidentes de seguridad y avisos enviados",
             plazo=_days_text(INCIDENTES_DIAS), desde="Cierre del incidente", accion="Supresión",
             fundamento="LFPDPPP arts. 18 y 19", aplicacion="automatica", dias=INCIDENTES_DIAS),
        dict(clave="bitacora_admin", ref="R36", categoria="Bitácora de acciones del personal administrador",
             plazo=f"{_days_text(BITACORA_ADMIN_DIAS)}; la IP se acorta a los {IP_RECORTE_DIAS} días",
             desde="Registro", accion="Supresión", fundamento="LFPDPPP arts. 13 y 18", aplicacion="automatica",
             dias=BITACORA_ADMIN_DIAS),
        dict(clave="registros_otp_ip", ref="R37",
             categoria="Registros técnicos con IP guardados en la base (envíos de códigos, formularios públicos)",
             plazo=f"{_days_text(REGISTROS_TECNICOS_DIAS)}; IP acortada a los {IP_RECORTE_DIAS} días",
             desde="Registro", accion="Supresión", fundamento="LFPDPPP arts. 2 fr. V, 10 y 12",
             aplicacion="automatica", dias=REGISTROS_TECNICOS_DIAS),
        dict(clave="registros_servidor", ref="R37", categoria="Registros del servidor web y de la aplicación",
             plazo="Rotación por tamaño del servidor (meta: 90 días)", desde="Registro", accion="Rotación y borrado",
             fundamento="LFPDPPP arts. 2 fr. V, 10 y 12", aplicacion="procedimiento"),
        dict(clave="registro_purgas", categoria="Registro de las purgas automáticas de esta tabla",
             plazo=_days_text(REGISTRO_PURGAS_DIAS), desde="Corrida", accion="Supresión",
             fundamento="LFPDPPP arts. 13 y 18 (evidencia de cumplimiento)", aplicacion="automatica",
             dias=REGISTRO_PURGAS_DIAS),
        dict(clave="respaldos", ref="R38", categoria="Respaldos cifrados de la base de datos y de los archivos",
             plazo=f"Copia local {_days_text(local_backups)}; copia externa {_days_text(offsite_backups)}",
             desde="Fecha del respaldo", accion="Caducidad automática", fundamento="LFPDPPP arts. 10, 13 y 18",
             aplicacion="caduca_sola", tarea="scripts/backup.sh y scripts/backup-offsite.sh"),
        dict(clave="analitica", ref="R39", categoria="Analítica (PostHog, solo si la aceptas) y errores (Sentry)",
             plazo="PostHog 12 meses; Sentry según su plan", desde="Evento", accion="Purga del proveedor",
             fundamento="LFPDPPP art. 12", aplicacion="proveedor"),
        dict(clave="cookies", ref="R40", categoria="Tu elección de cookies (patitas_consent)",
             plazo="12 meses o hasta que cambie la política", desde="Elección", accion="Te volvemos a preguntar",
             fundamento="Buena práctica", aplicacion="navegador"),
        dict(clave="cuentas_sancionadas", ref="R42",
             categoria=("Correo, teléfono y cuenta de Google de una cuenta cancelada por incumplir las reglas (se "
                        "quedan en su perfil, sin copia aparte, para impedir que se vuelva a registrar)"),
             plazo=f"Mientras la cancelación siga vigente, máximo {_days_text(SANCIONADAS_DIAS)}",
             desde="Cancelación de la cuenta", accion="Se borran del perfil cancelado (ya no impiden un registro nuevo)",
             fundamento="LFPDPPP arts. 10 y 12", aplicacion="automatica", dias=SANCIONADAS_DIAS),
    ]
    for row in rows:
        row.setdefault("ref", None)
        row.setdefault("dias", None)
        row.setdefault("tarea", "app.tasks.retention.run_retention" if row["aplicacion"] == "automatica" else None)
        row["aplicacion_texto"] = APLICACION_TEXTO[row["aplicacion"]]
    return rows


APLICACION_TEXTO = {
    "automatica": "Automática (tarea diaria)",
    "caduca_sola": "Vence sola",
    "al_eliminar": "Al eliminar la cuenta o el dato",
    "bloqueo": "Bloqueo por obligación legal",
    "procedimiento": "Procedimiento interno",
    "proveedor": "La aplica el proveedor",
    "navegador": "En tu navegador",
    "no_se_guarda": "No se guarda",
}
PUBLIC_FIELDS = ("clave", "ref", "categoria", "plazo", "desde", "accion", "fundamento", "aplicacion", "aplicacion_texto")


def category(clave: str) -> dict:
    for row in categories():
        if row["clave"] == clave:
            return row
    raise KeyError(clave)


def plazo_dias(clave: str) -> int | None:
    """Días del plazo de una categoría (lo usan otras tareas para no duplicar números)."""
    return category(clave)["dias"]


# --------------------------------------------------------------------------- utilidades
def truncate_ip(value: str | None) -> str | None:
    """IPv4 a /24 (a.b.c.0) e IPv6 a /48 (a:b:c::). Lo que no es IP queda igual."""
    if not value:
        return value
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return value
    if ip.version == 4:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False).network_address)
    return str(ipaddress.ip_network(f"{ip}/48", strict=False).network_address)


def freeze_until(incident) -> datetime.datetime | None:
    """Hasta cuándo congela las purgas ese incidente (None si no las congela). Sin fecha guardada (registros
    anteriores al tope) cuenta desde que se detectó."""
    if not incident.freeze_purges or incident.status == "cerrado":
        return None
    if incident.freeze_purges_until is not None:
        return incident.freeze_purges_until
    start = incident.detected_at or incident.created_at or datetime.datetime.utcnow()
    return start + datetime.timedelta(days=FREEZE_MAX_DIAS)


def freezing_incidents(db: Session, now: datetime.datetime | None = None) -> list:
    """Incidentes sin cerrar cuyo congelamiento de purgas sigue vigente (runbook §5 paso 2), con el tope de 30 días."""
    from app.models import SecurityIncident

    now = now or datetime.datetime.utcnow()
    legacy_since = now - datetime.timedelta(days=FREEZE_MAX_DIAS)
    return db.query(SecurityIncident).filter(
        SecurityIncident.freeze_purges.is_(True), SecurityIncident.status != "cerrado",
        or_(SecurityIncident.freeze_purges_until > now,
            and_(SecurityIncident.freeze_purges_until.is_(None), SecurityIncident.detected_at > legacy_since)),
    ).all()


def purges_frozen(db: Session, now: datetime.datetime | None = None) -> bool:
    """True si hay un incidente sin cerrar con el congelamiento de purgas vigente."""
    return bool(freezing_incidents(db, now))


def freeze_covers_documents(incidents) -> bool:
    """¿Algún incidente que congela incluye identificaciones o documentos privados en lo afectado?"""
    for inc in incidents:
        for value in [*(inc.systems_affected or []), *(inc.data_categories or [])]:
            text = str(value or "").lower()
            words = set(re.split(r"[^a-z0-9áéíóúñ]+", text))
            if any(h in text for h in FREEZE_DOC_HINTS) or FREEZE_DOC_WORDS & words:
                return True
    return False


def freeze_status(db: Session, now: datetime.datetime | None = None) -> dict:
    """Estado del congelamiento para el panel: hasta cuándo, por qué incidentes y qué sigue corriendo."""
    incidents = freezing_incidents(db, now)
    until = max((freeze_until(i) for i in incidents), default=None)
    covers = freeze_covers_documents(incidents)
    return {"congelada": bool(incidents), "hasta": until, "incidentes": [i.folio or i.id for i in incidents],
            "max_dias": FREEZE_MAX_DIAS, "documentos_incluidos": covers,
            "siguen_corriendo": [] if (covers or not incidents) else list(FREEZE_EXEMPT)}


class PurgeContext:
    """Estado de una corrida: en simulación (dry_run) no se borra ningún archivo y la base se revierte."""

    def __init__(self, db: Session, now: datetime.datetime, dry_run: bool = False):
        self.db, self.now, self.dry_run = db, now, dry_run

    def ago(self, days: int) -> datetime.datetime:
        return self.now - datetime.timedelta(days=days)

    def delete_private(self, doc_id: str | None) -> int:
        if not doc_id:
            return 0
        if self.dry_run:
            from app.routers.documents import private_document_path

            return int(private_document_path(doc_id) is not None)
        from app.routers.documents import delete_private_document

        return int(delete_private_document(doc_id))

    def delete_fiscal_file(self, doc_id: str | None) -> int:
        from app.services import invoicing

        path = invoicing.fiscal_file_path(doc_id)
        if not path:
            return 0
        if self.dry_run:
            return 1
        try:
            path.unlink()
            return 1
        except OSError as exc:
            logger.warning("No se pudo borrar %s: %s", path.name, exc)
            return 0

    def delete_uploads(self, owner_id: int | None, urls) -> int:
        """Fotos públicas (/uploads/...) que nadie más usa."""
        from app.services.account_deletion import delete_upload_files, referenced_uploads, upload_name

        urls = [u for u in (urls or []) if u]
        if not urls:
            return 0
        if self.dry_run:
            names = {n for n in (upload_name(u) for u in urls) if n}
            return len(names - referenced_uploads(self.db, names, exclude_user_id=owner_id or 0))
        return delete_upload_files(self.db, owner_id or 0, urls)

    def audit(self, action: str, target_type: str, target_id: int | None, details: dict | None = None) -> None:
        from app.services.audit import record_admin_action

        record_admin_action(self.db, None, action, target_type, target_id, details=details)


def _legal_hold_ids(db: Session, target_types: tuple[str, ...]) -> set[int]:
    """Ids con retención legal en la bóveda de evidencia (no se borran ni se anonimizan)."""
    try:
        from app.models import EvidenceRecord
    except ImportError:
        return set()
    rows = db.query(EvidenceRecord.target_id).filter(
        EvidenceRecord.target_type.in_(target_types), EvidenceRecord.legal_hold.is_(True),
        EvidenceRecord.target_id.isnot(None)).all()
    return {r for (r,) in rows}


# --------------------------------------------------------------------------- purgas
def purge_verification_documents(ctx: PurgeContext) -> dict:
    """R15/R17: imágenes de INE, acta o cédula 30 días después de aprobar o rechazar; queda la constancia."""
    from app.models import AdminAuditLog, Refuge, Veterinary
    from app.routers.documents import is_document_id

    db, cutoff = ctx.db, ctx.ago(DOCUMENTOS_VERIFICACION_DIAS)
    stats = {"refugios": 0, "clinicas": 0, "archivos": 0, "fechas_registradas": 0}
    # Refugios: la decisión es la última aprobación o rechazo de la bitácora (o la que ya quedó anotada)
    refuges = db.query(Refuge).filter(
        Refuge.status.in_(("approved", "rejected")), Refuge.documents_purged_at.is_(None),
        cast(Refuge.documents, String) != "[]").order_by(Refuge.id).limit(BATCH).all()
    for refuge in refuges:
        if not refuge.documents:
            continue
        decided = refuge.verification_decided_at
        if decided is None:
            decided = db.query(func.max(AdminAuditLog.created_at)).filter(
                AdminAuditLog.target_type == "refuge", AdminAuditLog.target_id == refuge.id,
                AdminAuditLog.action.in_(("refuge.approve", "refuge.reject"))).scalar()
            # Sin rastro en la bitácora (decisiones anteriores a ella): el plazo corre desde hoy
            refuge.verification_decided_at = decided or ctx.now
            stats["fechas_registradas"] += 1
        if refuge.verification_decided_at >= cutoff:
            continue
        files, legacy = 0, []
        for doc in refuge.documents or []:
            if isinstance(doc, str) and is_document_id(doc):
                files += ctx.delete_private(doc)
            elif isinstance(doc, str):
                legacy.append(doc)
        files += ctx.delete_uploads(refuge.user_id, legacy)
        count = len(refuge.documents or [])
        refuge.documents = []
        refuge.documents_purged_at = ctx.now
        ctx.audit("retention.refuge_documents_purged", "refuge", refuge.id,
                  {"documents": count, "files": files, "decided_at": refuge.verification_decided_at.isoformat(),
                   "status": refuge.status})
        stats["refugios"] += 1
        stats["archivos"] += files
    # Clínicas: verificada (verified_at) o rechazada (unpublished_at del rechazo)
    vets = db.query(Veterinary).filter(
        Veterinary.cedula_document_id.isnot(None),
        or_((Veterinary.status == "verified") & (Veterinary.verified_at < cutoff),
            (Veterinary.status == "rejected") & (Veterinary.unpublished_at < cutoff)),
    ).order_by(Veterinary.id).limit(BATCH).all()
    for vet in vets:
        files = ctx.delete_private(vet.cedula_document_id)
        verified = vet.status == "verified"
        vet.cedula_document_id = None
        # Tras verificar queda la constancia (la clínica puede editar su ficha sin volver a subirla); tras un
        # rechazo, para volver a enviarla hay que subir la cédula otra vez
        vet.cedula_document_purged_at = ctx.now if verified else None
        ctx.audit("retention.cedula_purged", "veterinary", vet.id, {"status": vet.status, "files": files})
        stats["clinicas"] += 1
        stats["archivos"] += files
    return stats


def _referenced_private_names(db: Session, names: set[str]) -> set[str]:
    """Nombres de `names` que aparecen en alguna columna de la base que guarda documentos o archivos.

    Se revisan todas las columnas de texto o JSON cuyo nombre sugiere un archivo (document, file, path,
    evidence, xml, pdf...), así un módulo nuevo que guarde el id de un documento privado lo protege solo.
    """
    from sqlalchemy import select

    from app.database import Base

    ref_re = re.compile(r"(document|file|path|evidence|attach|xml|pdf|storage|csf|cedula|blob)", re.I)
    found: set[str] = set()
    names_list = sorted(names)
    for table in Base.metadata.sorted_tables:
        cols = [c for c in table.columns if ref_re.search(c.name)
                and isinstance(c.type, (String, Text, JSON)) and type(c.type).__name__ != "EncryptedText"]
        for col in cols:
            for i in range(0, len(names_list), 50):
                batch = names_list[i:i + 50]
                as_text = cast(col, Text)
                rows = db.execute(select(as_text).where(or_(*[as_text.like(f"%{n}%") for n in batch]))).all()
                for (value,) in rows:
                    found.update(n for n in batch if value and n in value)
    return found


def _known_private_refs(db: Session) -> set[str]:
    """Ids de documentos privados que usan las tablas conocidas (consulta rápida antes de la revisión general)."""
    from app.models import Cfdi, OrderInvoice, Refuge, RefugeFiscalProfile, Veterinary

    refs: set[str] = set()
    for (docs,) in db.query(Refuge.documents).filter(cast(Refuge.documents, String) != "[]").all():
        refs.update(d for d in (docs or []) if isinstance(d, str))
    for cols in ((Veterinary.cedula_document_id, Veterinary.verification_evidence_document_id),
                 (RefugeFiscalProfile.csf_document_id,), (OrderInvoice.xml_document_id, OrderInvoice.pdf_document_id),
                 (Cfdi.xml_document_id, Cfdi.pdf_document_id)):
        for row in db.query(*cols).all():
            refs.update(v for v in row if v)
    return refs


def purge_abandoned_documents(ctx: PurgeContext) -> dict:
    """Documentos privados que nadie usa (formularios abandonados) con más de 7 días."""
    from app.routers.documents import is_document_id, private_dir
    from app.services import invoicing

    cutoff = (ctx.ago(DOCUMENTOS_ABANDONADOS_DIAS) - datetime.datetime(1970, 1, 1)).total_seconds()
    known = _known_private_refs(ctx.db)
    candidates = set()
    leftovers = 0
    for path in private_dir().iterdir():
        # Temporales de una escritura interrumpida (crypto_storage.write_private): se borran al día siguiente
        if path.name.startswith(".tmp-") and path.is_file():
            try:
                if path.stat().st_mtime < cutoff + (DOCUMENTOS_ABANDONADOS_DIAS - 1) * 86400:
                    if not ctx.dry_run:
                        path.unlink()
                    leftovers += 1
            except OSError:
                pass
            continue
        if path.name in known or not path.is_file() or not (
                is_document_id(path.name) or invoicing.is_fiscal_file_id(path.name)):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                candidates.add(path.name)
        except OSError:
            continue
        if len(candidates) >= BATCH:
            break
    if not candidates:
        return {"archivos": 0, "temporales": leftovers}
    orphans = candidates - _referenced_private_names(ctx.db, candidates)
    deleted = 0
    for name in sorted(orphans):
        deleted += ctx.delete_private(name) if is_document_id(name) else ctx.delete_fiscal_file(name)
    return {"archivos": deleted, "revisados": len(candidates), "temporales": leftovers}


def purge_fiscal_constancias(ctx: PurgeContext) -> dict:
    """R09: la Constancia de Situación Fiscal se conserva 10 años desde la última operación del Refugio."""
    from app.models import Cfdi, Donation, Order, Refuge, RefugeFiscalProfile

    db = ctx.db
    stats = {"constancias": 0}
    rows = db.query(RefugeFiscalProfile, Refuge).join(Refuge, Refuge.id == RefugeFiscalProfile.refuge_id).filter(
        RefugeFiscalProfile.csf_document_id.isnot(None)).order_by(RefugeFiscalProfile.id).limit(BATCH).all()
    for profile, refuge in rows:
        last_ops = [
            db.query(func.max(Order.paid_at)).filter(Order.refuge_id == refuge.id).scalar(),
            db.query(func.max(Donation.created_at)).filter(Donation.refuge_id == refuge.id,
                                                          Donation.status.in_(("approved", "refunded"))).scalar(),
            db.query(func.max(Cfdi.created_at)).filter(Cfdi.refuge_id == refuge.id).scalar(),
        ]
        last_op = max((d for d in last_ops if d), default=None)
        expired = (last_op is not None and last_op < ctx.ago(EXPEDIENTE_FISCAL_DIAS)) or (
            last_op is None and refuge.status == "closed" and (profile.updated_at or profile.created_at)
            < ctx.ago(CSF_SIN_OPERACIONES_DIAS))
        if not expired:
            continue
        files = ctx.delete_private(profile.csf_document_id)
        profile.csf_document_id = None
        ctx.audit("retention.csf_purged", "refuge", refuge.id,
                  {"files": files, "last_operation": last_op.isoformat() if last_op else None})
        stats["constancias"] += 1
    return stats


def purge_deleted_account_chats(ctx: PurgeContext) -> dict:
    """R21: mensajes de conversaciones con una cuenta eliminada hace más de 90 días (salvo reporte o retención)."""
    from app.models import ContentReport, Conversation, Message, User

    db = ctx.db
    deleted_users = db.query(User.id).filter(User.deleted_at.isnot(None),
                                             User.deleted_at < ctx.ago(CHATS_CUENTA_ELIMINADA_DIAS))
    convs = db.query(Conversation).filter(
        or_(Conversation.user_a_id.in_(deleted_users), Conversation.user_b_id.in_(deleted_users)),
        Conversation.id.in_(db.query(Message.conversation_id)),
    ).order_by(Conversation.id).limit(BATCH).all()
    held_convs = _legal_hold_ids(db, ("conversation",))
    held_msgs = _legal_hold_ids(db, ("message",))
    stats = {"conversaciones": 0, "mensajes": 0, "retenidas": 0}
    for conv in convs:
        msg_ids = [m for (m,) in db.query(Message.id).filter(Message.conversation_id == conv.id).all()]
        reported = db.query(ContentReport.id).filter(
            ContentReport.target_type == "message", ContentReport.target_id.in_(msg_ids),
            or_(ContentReport.status == "open", ContentReport.resolved_at.is_(None),
                ContentReport.resolved_at > ctx.ago(CHATS_CON_REPORTE_DIAS))).first() if msg_ids else None
        if reported or conv.id in held_convs or held_msgs.intersection(msg_ids):
            stats["retenidas"] += 1
            continue
        stats["mensajes"] += db.query(Message).filter(Message.conversation_id == conv.id).delete(
            synchronize_session=False)
        conv.last_message_at = None
        stats["conversaciones"] += 1
    return stats


def anonymize_closed_reports(ctx: PurgeContext) -> dict:
    """R23: reportes resueltos, caducados o cerrados hace 90 días: quedan ciudad, estado, tipo, fecha y resultado."""
    from app.models import ContentReport, LostReport

    db = ctx.db
    since = func.coalesce(LostReport.resolved_at, LostReport.updated_at, LostReport.last_activity_at,
                          LostReport.created_at)
    rows = db.query(LostReport).filter(
        LostReport.status.in_(("resolved", "expired", "closed")), LostReport.purged_at.is_(None),
        since < ctx.ago(REPORTES_ANONIMIZAR_DIAS)).order_by(LostReport.id).limit(BATCH).all()
    held = _legal_hold_ids(db, ("lost_report",))
    open_reports = {t for (t,) in db.query(ContentReport.target_id).filter(
        ContentReport.target_type == "lost_report", ContentReport.status == "open").all()}
    stats = {"reportes": 0, "fotos": 0, "retenidos": 0}
    for report in rows:
        if report.id in held or report.id in open_reports:
            stats["retenidos"] += 1
            continue
        stats["fotos"] += ctx.delete_uploads(report.reporter_id, list(report.photos or []))
        report.photos = []
        report.description = None
        report.contact_phone = None
        report.latitude = None
        report.longitude = None
        report.photo_signature = None
        report.ai_analysis = None
        report.dog_name = "Reporte anonimizado"
        report.reporter_id = None
        report.is_hidden = True
        report.purged_at = ctx.now
        stats["reportes"] += 1
    return stats


def purge_volunteer_consents(ctx: PurgeContext) -> dict:
    """R26: la prueba de autorización de un envío de voluntario, 2 años después de retirarse la publicación."""
    from app.models import LostReport

    rows = ctx.db.query(LostReport).filter(
        LostReport.source == "volunteer", LostReport.consent_at.isnot(None), LostReport.purged_at.isnot(None),
        LostReport.purged_at < ctx.ago(AUTORIZACION_VOLUNTARIOS_DIAS)).limit(BATCH).all()
    for report in rows:
        report.consent_at = None
        report.consent_version = None
    return {"reportes": len(rows)}


def purge_bot_interactions(ctx: PurgeContext) -> dict:
    """R27: interacciones con el bot de más de 12 meses; de los números dados de baja solo queda la baja."""
    from app.models import BotInteraction

    db = ctx.db
    old = BotInteraction.updated_at < ctx.ago(BOT_DIAS)
    removed = db.query(BotInteraction).filter(old, BotInteraction.opted_out_at.is_(None)).delete(
        synchronize_session=False)
    kept = 0
    for row in db.query(BotInteraction).filter(old, BotInteraction.opted_out_at.isnot(None),
                                               or_(BotInteraction.last_message.isnot(None),
                                                   cast(BotInteraction.data, String) != "{}")).limit(BATCH).all():
        row.data = {}
        row.last_message = None
        kept += 1
    return {"borradas": removed, "bajas_conservadas": kept}


def anonymize_moderation_reports(ctx: PurgeContext) -> dict:
    """R32: reportes de moderación resueltos hace 24 meses (10 años si involucran a menores: prioridad 0)."""
    from app.models import ContentReport

    db = ctx.db
    has_personal = or_(ContentReport.reporter_id.isnot(None), ContentReport.details.isnot(None),
                       ContentReport.admin_notes.isnot(None), ContentReport.contact_email.isnot(None),
                       ContentReport.reporter_ip.isnot(None))
    rows = db.query(ContentReport).filter(
        ContentReport.status.in_(("resolved", "dismissed")), ContentReport.resolved_at.isnot(None), has_personal,
        or_((ContentReport.priority != 0) & (ContentReport.resolved_at < ctx.ago(MODERACION_DIAS)),
            ContentReport.resolved_at < ctx.ago(MODERACION_MENORES_DIAS)),
    ).limit(BATCH).all()
    for row in rows:
        row.reporter_id = None
        row.details = None
        row.admin_notes = None
        row.contact_email = None
        row.reporter_ip = None
        row.target_url = None
    return {"reportes": len(rows)}


def expire_sanction_fingerprints(ctx: PurgeContext) -> dict:
    """R42: a los 24 meses de cancelar una cuenta por incumplir las reglas se borran del perfil cancelado el
    teléfono, el correo y la cuenta de Google con los que se impedía volver a registrarse
    (legal_moderation.check_not_banned_phone y el correo único del registro)."""
    from sqlalchemy import exists

    from app.models import ModerationAction, User

    cutoff = ctx.ago(SANCIONADAS_DIAS)
    recent = exists().where(ModerationAction.user_id == User.id, ModerationAction.action == "cancel_account",
                            ModerationAction.status == "active", ModerationAction.created_at >= cutoff)
    old = exists().where(ModerationAction.user_id == User.id, ModerationAction.action == "cancel_account",
                         ModerationAction.status == "active", ModerationAction.created_at < cutoff)
    rows = (ctx.db.query(User).filter(
        User.is_active.is_(False), old, ~recent,
        or_(User.phone.isnot(None), User.google_sub.isnot(None), ~User.email.like("%@patitasfind.invalid")))
        .limit(BATCH).all())
    for user in rows:
        user.phone = None
        user.phone_verified = False
        user.phone_verified_at = None
        user.google_sub = None
        if not (user.email or "").endswith("@patitasfind.invalid"):
            user.email = f"cancelada-{user.id}@patitasfind.invalid"
        ctx.audit("retention.sanction_fingerprints", "user", user.id, {"plazo_dias": SANCIONADAS_DIAS})
    return {"cuentas": len(rows)}


def dissociate_sanctions(ctx: PurgeContext) -> dict:
    """R41: los datos de incumplimientos no se guardan más de 72 meses: la medida se desliga de la persona."""
    try:
        from app.models import ModerationAction
    except ImportError:
        return {"omitido": "sin medidas de moderación"}
    rows = ctx.db.query(ModerationAction).filter(
        ModerationAction.created_at < ctx.ago(INCUMPLIMIENTOS_DIAS),
        or_(ModerationAction.user_id.isnot(None), ModerationAction.notes.isnot(None))).limit(BATCH).all()
    for row in rows:
        row.user_id = None
        row.notes = None
        row.details = None
    return {"medidas": len(rows)}


def _truncate_ips(ctx: PurgeContext, model, ip_col: str, date_col: str, clear_after: int | None = None) -> int:
    col, when = getattr(model, ip_col), getattr(model, date_col)
    changed = 0
    if clear_after is not None:
        changed += ctx.db.query(model).filter(col.isnot(None), when < ctx.ago(clear_after)).update(
            {col: None}, synchronize_session=False)
    rows = ctx.db.query(model).filter(col.isnot(None), when < ctx.ago(IP_RECORTE_DIAS),
                                      ~col.like("%.0"), ~col.like("%::")).limit(BATCH).all()
    for row in rows:
        short = truncate_ip(getattr(row, ip_col))
        if short != getattr(row, ip_col):
            setattr(row, ip_col, short)
            changed += 1
    return changed


def purge_technical_logs(ctx: PurgeContext) -> dict:
    """R37: registros de envíos de código y formularios públicos: 90 días, IP acortada a los 30."""
    from app.models import ContentReport, PhoneVerificationLog

    db = ctx.db
    stats = {"envios_borrados": db.query(PhoneVerificationLog).filter(
        PhoneVerificationLog.created_at < ctx.ago(REGISTROS_TECNICOS_DIAS)).delete(synchronize_session=False)}
    stats["ips_envios"] = _truncate_ips(ctx, PhoneVerificationLog, "ip", "created_at")
    stats["ips_reportes"] = _truncate_ips(ctx, ContentReport, "reporter_ip", "created_at", REGISTROS_TECNICOS_DIAS)
    try:
        from app.models import ModerationAppeal

        stats["ips_apelaciones"] = _truncate_ips(ctx, ModerationAppeal, "ip", "created_at", REGISTROS_TECNICOS_DIAS)
    except ImportError:
        pass
    return stats


def purge_admin_audit(ctx: PurgeContext) -> dict:
    """R36: bitácora de administración 5 años; la IP se acorta a los 30 días."""
    from app.models import AdminAuditLog

    removed = ctx.db.query(AdminAuditLog).filter(AdminAuditLog.created_at < ctx.ago(BITACORA_ADMIN_DIAS)).delete(
        synchronize_session=False)
    return {"borrados": removed, "ips": _truncate_ips(ctx, AdminAuditLog, "ip", "created_at")}


def purge_notifications(ctx: PurgeContext) -> dict:
    from app.models import Notification

    return {"borradas": ctx.db.query(Notification).filter(
        Notification.created_at < ctx.ago(NOTIFICACIONES_DIAS)).delete(synchronize_session=False)}


def purge_adoption_answers(ctx: PurgeContext) -> dict:
    """R19: respuestas del cuestionario de postulaciones ya cerradas con más de 12 meses."""
    from app.models import AdoptionApplication

    rows = ctx.db.query(AdoptionApplication).filter(
        AdoptionApplication.status != "pending", AdoptionApplication.created_at < ctx.ago(CUESTIONARIOS_DIAS),
        cast(AdoptionApplication.answers, String) != "{}").limit(BATCH).all()
    for row in rows:
        row.answers = {}
    return {"cuestionarios": len(rows)}


def anonymize_shipping(ctx: PurgeContext) -> dict:
    """R06: domicilio y teléfono de envío, al vencer el plazo de reclamación más 1 año."""
    from app.models import Order

    days = settings.return_claim_window_days + ENVIO_ANONIMIZAR_EXTRA_DIAS
    since = func.coalesce(Order.delivered_at, Order.completed_at, Order.cancelled_at, Order.refunded_at)
    rows = ctx.db.query(Order).filter(
        since.isnot(None), since < ctx.ago(days),
        or_(Order.shipping_phone.isnot(None), Order.shipping_street.isnot(None),
            Order.shipping_references.isnot(None), Order.shipping_address != "Dirección anonimizada"),
    ).limit(BATCH).all()
    for order in rows:
        order.shipping_phone = None
        order.shipping_street = None
        order.shipping_ext_number = None
        order.shipping_int_number = None
        order.shipping_neighborhood = None
        order.shipping_references = None
        order.shipping_address = "Dirección anonimizada"
    return {"pedidos": len(rows)}


RESIDUAL_USER_FIELDS = ("terms_accepted_at", "terms_version", "privacy_version", "birth_date", "adult_declared_at",
                        "age_check_status", "google_sub", "avatar_url", "city", "country", "latitude", "longitude",
                        "phone", "phone_verified_at", "email_verified_at", "mfa_secret_enc", "mfa_pending_secret_enc",
                        "mfa_enabled_at", "mfa_last_step")


def purge_deleted_account_minimums(ctx: PurgeContext) -> dict:
    """R02: datos residuales de cuentas eliminadas: 1 año sin compras ni donativos; 10 años con ellas."""
    from app.models import Donation, Order, User

    db = ctx.db
    rows = db.query(User).filter(User.deleted_at.isnot(None),
                                 User.deleted_at < ctx.ago(CUENTA_MINIMOS_DIAS)).order_by(User.id).limit(BATCH).all()
    cleaned = 0
    for user in rows:
        fields = [f for f in RESIDUAL_USER_FIELDS if hasattr(User, f) and getattr(user, f) is not None]
        if not fields:
            continue
        operated = (db.query(Order.id).filter(Order.user_id == user.id, Order.paid_at.isnot(None)).first()
                    or db.query(Donation.id).filter(Donation.user_id == user.id, Donation.status == "approved").first())
        if operated and user.deleted_at >= ctx.ago(CUENTA_MINIMOS_CON_OPERACIONES_DIAS):
            continue
        for field in fields:
            setattr(user, field, None)
        cleaned += 1
    return {"cuentas": cleaned}


def purge_evidence(ctx: PurgeContext) -> dict:
    """R30: la bóveda (services/evidence.py) borra lo vencido sin retención legal; el material de abuso nunca."""
    try:
        from app.services import evidence
    except ImportError:
        return {"omitido": "la bóveda de evidencia no está instalada"}
    if ctx.dry_run:
        return {"omitido": "simulación"}
    for name in ("purge_expired", "purge_expired_evidence", "purge"):
        fn = getattr(evidence, name, None)
        if callable(fn):
            try:
                result = fn(ctx.db, now=ctx.now)
            except TypeError:
                result = fn(ctx.db)
            return result if isinstance(result, dict) else {"resultado": result}
    return {"omitido": "services/evidence.py no expone purge_expired"}


def purge_incidents(ctx: PurgeContext) -> dict:
    """R35: incidentes cerrados hace más de 5 años, con sus avisos."""
    from app.models import SecurityIncident, SecurityIncidentNotice

    ids = [i for (i,) in ctx.db.query(SecurityIncident.id).filter(
        SecurityIncident.status == "cerrado", SecurityIncident.closed_at < ctx.ago(INCIDENTES_DIAS)).all()]
    if not ids:
        return {"incidentes": 0}
    ctx.db.query(SecurityIncidentNotice).filter(SecurityIncidentNotice.incident_id.in_(ids)).delete(
        synchronize_session=False)
    ctx.db.query(SecurityIncident).filter(SecurityIncident.id.in_(ids)).delete(synchronize_session=False)
    return {"incidentes": len(ids)}


def purge_retention_runs(ctx: PurgeContext) -> dict:
    from app.models import RetentionRun

    return {"corridas": ctx.db.query(RetentionRun).filter(
        RetentionRun.started_at < ctx.ago(REGISTRO_PURGAS_DIAS)).delete(synchronize_session=False)}


# Orden de ejecución: primero lo que libera archivos de verificación, al final los registros
PURGERS = (
    ("documentos_verificacion", purge_verification_documents),
    ("documentos_abandonados", purge_abandoned_documents),
    ("expediente_fiscal_refugio", purge_fiscal_constancias),
    ("chats_cuentas_eliminadas", purge_deleted_account_chats),
    ("reportes_anonimizar", anonymize_closed_reports),
    ("autorizacion_voluntarios", purge_volunteer_consents),
    ("bot_whatsapp", purge_bot_interactions),
    ("moderacion", anonymize_moderation_reports),
    ("cuentas_sancionadas", expire_sanction_fingerprints),
    ("incumplimientos", dissociate_sanctions),
    ("registros_otp_ip", purge_technical_logs),
    ("bitacora_admin", purge_admin_audit),
    ("notificaciones", purge_notifications),
    ("cuestionarios_adopcion", purge_adoption_answers),
    ("envio_comprador", anonymize_shipping),
    ("cuenta_eliminada_minimos", purge_deleted_account_minimums),
    ("boveda_evidencia", purge_evidence),
    ("incidentes", purge_incidents),
    ("registro_purgas", purge_retention_runs),
)


def run_purge(db: Session, now: datetime.datetime | None = None, dry_run: bool = False,
              only: tuple[str, ...] | None = None, force: bool = False) -> dict:
    """Aplica la tabla de conservación. Cada categoría va en su propia transacción: si una falla, las demás siguen.

    force=True ignora la pausa por incidente (solo pruebas o una orden expresa del líder del incidente).
    """
    from app.models import RetentionRun

    now = now or datetime.datetime.utcnow()
    run = RetentionRun(started_at=now, status="running", dry_run=dry_run)
    if not settings.retention_purge_enabled and not force:
        run.status, run.finished_at, run.results = "disabled", datetime.datetime.utcnow(), {}
        db.add(run)
        db.commit()
        logger.warning("Purga de conservación desactivada (RETENTION_PURGE_ENABLED=false).")
        return {"status": "disabled", "results": {}}
    frozen = freezing_incidents(db, now) if not force else []
    allowed = None
    if frozen:
        # Congelada por un incidente: solo siguen las identificaciones y documentos de verificación (borrado a los
        # 30 días que prometen las páginas), salvo que el incidente los incluya en lo afectado
        allowed = () if freeze_covers_documents(frozen) else FREEZE_EXEMPT
        logger.warning("Purga de conservación en pausa por un incidente abierto (%s); siguen: %s.",
                       ", ".join(str(i.folio or i.id) for i in frozen), ", ".join(allowed) or "nada")
        if not allowed:
            run.status, run.finished_at, run.results = "frozen", datetime.datetime.utcnow(), {}
            db.add(run)
            db.commit()
            return {"status": "frozen", "results": {}}
    ctx = PurgeContext(db, now, dry_run)
    results: dict = {}
    status = "frozen" if frozen else "ok"
    for clave, fn in PURGERS:
        if only and clave not in only:
            continue
        if allowed is not None and clave not in allowed:
            continue
        try:
            results[clave] = fn(ctx)
            if dry_run:
                db.rollback()
            else:
                db.commit()
        except Exception as exc:  # noqa: BLE001 - una categoría con error no detiene las demás
            db.rollback()
            logger.exception("Falló la purga de conservación de %s", clave)
            results[clave] = {"error": exc.__class__.__name__}
            status = "error"
    run.status, run.finished_at, run.results = status, datetime.datetime.utcnow(), results
    db.add(run)
    db.commit()
    changed = {k: v for k, v in results.items() if any(isinstance(n, int) and n for n in v.values())}
    if changed:
        logger.info("Purga de conservación%s: %s", " (simulación)" if dry_run else "", changed)
    return {"status": status, "results": results, "run_id": run.id}


def last_run(db: Session):
    from app.models import RetentionRun

    return db.query(RetentionRun).filter(RetentionRun.dry_run.is_(False)).order_by(RetentionRun.id.desc()).first()


def public_table(db: Session | None = None) -> dict:
    """Respuesta de GET /cumplimiento/conservacion."""
    rows = [{k: row[k] for k in PUBLIC_FIELDS} for row in categories()]
    out = {"version": VERSION, "generado": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
           "categorias": rows, "purga": None}
    if db is not None:
        run = last_run(db)
        out["purga"] = {
            "activa": bool(settings.retention_purge_enabled) and not purges_frozen(db),
            "congelada_hasta": _iso_z(freeze_status(db)["hasta"]),
            "ultima": (run.started_at.replace(microsecond=0).isoformat() + "Z") if run else None,
            "estado": {"ok": "completa", "error": "con errores", "frozen": "en pausa", "disabled": "en pausa",
                       "running": "en curso"}.get(run.status, run.status) if run else None,
        }
    return out


def _iso_z(value: datetime.datetime | None) -> str | None:
    return value.replace(microsecond=0).isoformat() + "Z" if value else None


def upload_dir() -> Path:
    return Path(settings.upload_dir)
