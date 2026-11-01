"""Facturación de la tienda (CFDI 4.0).

Modelo B (fiscal-tienda-08): el refugio vendedor emite el CFDI de cada producto al comprador que lo pide
(lo sube como XML y PDF); GuauWoow emite a cada refugio, por mes:
- CFDI de ingreso por su comisión (IVA 16 %) — fiscal-tienda-17; donativos-03.
- CFDI de retenciones e información de pagos 2.0 (complemento de plataformas tecnológicas) cuando retuvo
  ISR/IVA — fiscal-tienda-09 y 10 (dentro de los 5 días siguientes al mes: la tarea corre el día 3).

El PAC es intercambiable (PacAdapter.issue_cfdi(payload) -> {uuid, xml_bytes, pdf_bytes}); hoy existe
FacturamaAdapter (REST, Basic auth). Sin PAC_PROVIDER los registros quedan "pending_pac" y no se envía nada.
Las claves SAT marcadas "confirmar con el contador" deben validarse antes de timbrar en producción.
"""
import base64
import datetime
import logging
import re
import uuid as uuidlib
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Cfdi, Refuge
from app.routers.documents import private_dir
from app.services.payment_flow import money2
from app.services.statements import has_activity, previous_period, refuge_statement

logger = logging.getLogger(__name__)

# Archivos fiscales privados: PDF de POST /upload/document o XML de POST /upload/cfdi-xml
FISCAL_FILE_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|xml)$")
MAX_XML_BYTES = 2 * 1024 * 1024
IVA_RATE = Decimal("0.16")
# Confirmar con el contador: clave de producto/servicio y forma de pago de la comisión cobrada vía split
COMMISSION_PRODUCT_CODE = "80141600"  # Actividades de ventas y promoción de negocios
COMMISSION_UNIT_CODE = "E48"  # Unidad de servicio
COMMISSION_PAYMENT_FORM = "31"  # Intermediario pagos (la comisión la separa Mercado Pago en cada venta)
RETENTION_KEY = "26"  # c_CveRetenc: servicios mediante plataformas tecnológicas (confirmar con el PAC)
NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"


class PacError(RuntimeError):
    pass


def _now():
    return datetime.datetime.utcnow()


# --------------------------------------------------------------------------- archivos privados
def is_fiscal_file_id(value: str | None) -> bool:
    return bool(FISCAL_FILE_RE.match(value or ""))


def fiscal_file_path(doc_id: str | None) -> Path | None:
    if not is_fiscal_file_id(doc_id):
        return None
    folder = private_dir()
    candidate = folder / doc_id
    try:
        if candidate.resolve().parent == folder.resolve() and candidate.is_file():
            return candidate
    except OSError:
        return None
    return None


def store_fiscal_file(data: bytes, ext: str) -> str:
    """Guarda un XML o PDF fiscal cifrado en reposo (crypto_storage); se lee con read_fiscal_file."""
    from app.services import crypto_storage

    doc_id = f"{uuidlib.uuid4().hex}.{ext}"
    crypto_storage.write_private(private_dir() / doc_id, data)
    return doc_id


def read_fiscal_file(doc_id: str | None) -> bytes | None:
    """Contenido en claro de un archivo fiscal privado (None si no existe)."""
    from app.services import crypto_storage

    path = fiscal_file_path(doc_id)
    return crypto_storage.read_private(path) if path else None


def parse_cfdi_xml(data: bytes) -> dict:
    """Valida que sea un CFDI timbrado y extrae UUID, RFC emisor/receptor y total. ValueError si no."""
    if not data or len(data) > MAX_XML_BYTES:
        raise ValueError("El XML está vacío o pesa más de 2 MB.")
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise ValueError("El XML no es un CFDI válido.")  # sin DTD ni entidades (XXE / billion laughs)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ValueError("El archivo no es un XML válido.")
    if not root.tag.endswith("}Comprobante"):
        raise ValueError("El XML no es un CFDI (falta el nodo Comprobante).")
    ns = root.tag[1:].split("}")[0]
    emisor = root.find(f"{{{ns}}}Emisor")
    receptor = root.find(f"{{{ns}}}Receptor")
    tfd = root.find(f".//{{{NS_TFD}}}TimbreFiscalDigital")
    if tfd is None or not tfd.get("UUID"):
        raise ValueError("El XML no está timbrado (falta el Timbre Fiscal Digital).")
    try:
        total = Decimal(root.get("Total") or "")
    except Exception:  # noqa: BLE001
        total = None
    return {
        "uuid": tfd.get("UUID").upper(),
        "emisor_rfc": (emisor.get("Rfc") or "").upper() if emisor is not None else None,
        "receptor_rfc": (receptor.get("Rfc") or "").upper() if receptor is not None else None,
        "total": total,
        "version": root.get("Version"),
    }


# --------------------------------------------------------------------------- PAC
class PacAdapter:
    """Interfaz de un PAC: issue_cfdi(payload) -> {"uuid", "xml_bytes", "pdf_bytes", "provider_ref"}."""

    name = "base"

    def issue_cfdi(self, payload: dict) -> dict:  # pragma: no cover - interfaz
        raise NotImplementedError


class FacturamaAdapter(PacAdapter):
    """Facturama API Web (un solo emisor: la cuenta de Facturama es la de GuauWoow).

    - POST /3/cfdis  (CFDI 4.0 de ingreso)  -> {"Id", "Complement": {"TaxStamp": {"Uuid"}}}
    - POST /2/retenciones (Retenciones 2.0)  -> {"Id", ... UUID del timbre}
    - GET  /cfdi/{xml|pdf}/issued/{Id}      -> {"Content": base64}
    Verificar las rutas y nombres de campos en el sandbox (PAC_SANDBOX=true) antes de producción.
    """

    name = "facturama"
    TIMEOUT = 30

    def __init__(self, user: str, password: str, sandbox: bool = True):
        self.base = "https://apisandbox.facturama.mx" if sandbox else "https://api.facturama.mx"
        self.auth = (user, password)

    def _request(self, method: str, path: str, **kwargs):
        try:
            resp = requests.request(method, f"{self.base}{path}", auth=self.auth, timeout=self.TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise PacError("No pudimos conectar con el PAC (Facturama).") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("Message") or body.get("message") or str(body.get("ModelState") or "")[:300]
            except ValueError:
                message = resp.text[:300]
            raise PacError(f"Facturama respondió {resp.status_code}: {message}")
        return resp.json() if resp.content else {}

    @staticmethod
    def _uuid(data: dict) -> str | None:
        complement = data.get("Complement") or data.get("Complemento") or {}
        stamp = complement.get("TaxStamp") or complement.get("TimbreFiscalDigital") or {}
        return stamp.get("Uuid") or stamp.get("UUID") or data.get("Uuid") or data.get("UUID")

    def _download(self, fmt: str, kind: str, provider_ref: str) -> bytes:
        path = f"/cfdi/{fmt}/issued/{provider_ref}" if kind == "comision" else f"/retenciones/{fmt}/{provider_ref}"
        data = self._request("GET", path)
        content = data.get("Content") if isinstance(data, dict) else None
        if not content:
            raise PacError(f"Facturama no devolvió el {fmt.upper()} del CFDI.")
        return base64.b64decode(content)

    def issue_cfdi(self, payload: dict) -> dict:
        kind = payload.get("_kind", "comision")
        body = {k: v for k, v in payload.items() if not k.startswith("_")}
        data = self._request("POST", "/3/cfdis" if kind == "comision" else "/2/retenciones", json=body)
        provider_ref = str(data.get("Id") or data.get("id") or "")
        uuid = self._uuid(data)
        if not provider_ref or not uuid:
            raise PacError("Facturama no devolvió el UUID del CFDI timbrado.")
        return {"uuid": uuid.upper(), "provider_ref": provider_ref,
                "xml_bytes": self._download("xml", kind, provider_ref),
                "pdf_bytes": self._download("pdf", kind, provider_ref)}


def get_adapter() -> PacAdapter | None:
    if not settings.pac_enabled:
        return None
    if settings.pac_provider == "facturama":
        return FacturamaAdapter(settings.pac_user, settings.pac_password, settings.pac_sandbox)
    return None


# --------------------------------------------------------------------------- payloads
def commission_amounts(fee_with_iva) -> tuple[Decimal, Decimal, Decimal]:
    """La comisión se cobra con IVA incluido: (subtotal, iva, total)."""
    total = money2(fee_with_iva)
    subtotal = money2(total / (1 + IVA_RATE))
    return subtotal, total - subtotal, total


def build_commission_payload(cfdi: Cfdi, profile) -> dict:
    """CFDI 4.0 de ingreso por la comisión del periodo (formato JSON de Facturama /3/cfdis)."""
    subtotal, iva = Decimal(cfdi.subtotal), Decimal(cfdi.iva)
    return {
        "_kind": "comision",
        "Serie": settings.cfdi_serie,
        "Folio": str(cfdi.id),
        "CfdiType": "I",
        "NameId": "1",  # Factura
        "Currency": settings.currency,
        "ExpeditionPlace": settings.emisor_cp,
        "PaymentForm": COMMISSION_PAYMENT_FORM,
        "PaymentMethod": "PUE",
        "Exportation": "01",
        "Receiver": {
            "Rfc": profile.rfc,
            "Name": profile.legal_name,
            "CfdiUse": "G03",  # gastos en general
            "FiscalRegime": profile.regimen_fiscal,
            "TaxZipCode": profile.postal_code,
        },
        "Items": [{
            "ProductCode": COMMISSION_PRODUCT_CODE,
            "IdentificationNumber": f"COM-{cfdi.period}",
            "Description": f"Comisión por intermediación de ventas y donativos en GuauWoow, periodo {cfdi.period}",
            "Unit": "Unidad de servicio",
            "UnitCode": COMMISSION_UNIT_CODE,
            "UnitPrice": float(subtotal),
            "Quantity": 1,
            "Subtotal": float(subtotal),
            "TaxObject": "02",
            "Taxes": [{"Name": "IVA", "Rate": float(IVA_RATE), "Base": float(subtotal), "Total": float(iva),
                       "IsRetention": False}],
            "Total": float(subtotal + iva),
        }],
    }


def build_retention_payload(cfdi: Cfdi, profile, statement: dict) -> dict:
    """CFDI de retenciones 2.0 con complemento de plataformas tecnológicas (campos a confirmar con el PAC)."""
    year, month = cfdi.period.split("-")
    # Ventas del mes menos los reembolsos hechos en el mes (los de meses anteriores se descuentan aquí)
    gross = Decimal(statement.get("net_sales", statement["gross"]))
    base = gross if profile.is_donataria else money2(gross / (1 + IVA_RATE))
    iva_cobrado = gross - base
    retenidos = []
    if Decimal(cfdi.isr_retenido) > 0:
        retenidos.append({"BaseRet": float(base), "ImpuestoRet": "001", "MontoRet": float(cfdi.isr_retenido),
                          "TipoPagoRet": "01"})
    if Decimal(cfdi.iva_retenido) > 0:
        retenidos.append({"BaseRet": float(iva_cobrado), "ImpuestoRet": "002", "MontoRet": float(cfdi.iva_retenido),
                          "TipoPagoRet": "01"})
    return {
        "_kind": "retencion",
        "FolioInt": f"RET-{cfdi.id}",
        "FechaExp": _now().strftime("%Y-%m-%dT%H:%M:%S"),
        "LugarExpRetenc": settings.emisor_cp,
        "CveRetenc": RETENTION_KEY,
        "Emisor": {"RfcE": settings.emisor_rfc, "NomDenRazSocE": settings.emisor_nombre,
                   "RegimenFiscalE": settings.emisor_regimen},
        "Receptor": {"NacionalidadR": "Nacional",
                     "Nacional": {"RfcR": profile.rfc, "NomDenRazSocR": profile.legal_name,
                                  "DomicilioFiscalR": profile.postal_code}},
        "Periodo": {"MesIni": month, "MesFin": month, "Ejercicio": year},
        "Totales": {"MontoTotOperacion": float(gross), "MontoTotGrav": float(base),
                    "MontoTotExent": float(gross - base) if profile.is_donataria else 0.0,
                    "MontoTotRet": float(Decimal(cfdi.isr_retenido) + Decimal(cfdi.iva_retenido)),
                    "ImpRetenidos": retenidos},
        "Complemento": {"ServiciosPlataformasTecnologicas": {
            "Version": "1.0", "Periodicidad": "04", "NumServ": str(statement["orders_count"]),
            "MonTotServSIVA": float(base), "TotalIVATrasladado": float(iva_cobrado),
            "TotalIVARetenido": float(cfdi.iva_retenido), "TotalISRRetenido": float(cfdi.isr_retenido),
            "DifIVAEntregadoPrestServ": 0.0, "MonTotalporUsoPlataforma": float(statement["platform_fee"]),
        }},
    }


# --------------------------------------------------------------------------- emisión
def issue_cfdi_row(db: Session, cfdi: Cfdi, adapter: PacAdapter | None = None, statement: dict | None = None) -> Cfdi:
    """Timbra un registro pendiente o con error. Sin PAC queda "pending_pac" (no se envía nada). Hace commit."""
    if cfdi.status == "issued":
        return cfdi
    adapter = adapter or get_adapter()
    if adapter is None:
        cfdi.status = "pending_pac"
        db.commit()
        return cfdi
    refuge = db.query(Refuge).filter(Refuge.id == cfdi.refuge_id).first()
    profile = refuge.fiscal_profile if refuge else None
    cfdi.attempts = (cfdi.attempts or 0) + 1
    if not profile:
        cfdi.status = "error"
        cfdi.error = "El refugio no tiene perfil fiscal (RFC, razón social, régimen y CP)."
        db.commit()
        return cfdi
    try:
        if cfdi.kind == "comision":
            payload = build_commission_payload(cfdi, profile)
        else:
            payload = build_retention_payload(cfdi, profile, statement or refuge_statement(
                db, cfdi.refuge_id, cfdi.period, include_orders=False))
        result = adapter.issue_cfdi(payload)
    except PacError as exc:
        cfdi.status = "error"
        cfdi.error = str(exc)[:2000]
        db.commit()
        logger.warning("No se pudo timbrar el CFDI %s (%s %s): %s", cfdi.id, cfdi.kind, cfdi.period, exc)
        return cfdi
    cfdi.uuid = result["uuid"]
    cfdi.provider_ref = result.get("provider_ref")
    if result.get("xml_bytes"):
        cfdi.xml_document_id = store_fiscal_file(result["xml_bytes"], "xml")
    if result.get("pdf_bytes"):
        cfdi.pdf_document_id = store_fiscal_file(result["pdf_bytes"], "pdf")
    cfdi.status = "issued"
    cfdi.error = None
    cfdi.issued_at = _now()
    db.commit()
    return cfdi


def _upsert(db: Session, kind: str, period: str, refuge_id: int, amounts: dict) -> Cfdi:
    row = db.query(Cfdi).filter(Cfdi.kind == kind, Cfdi.period == period, Cfdi.refuge_id == refuge_id).first()
    if row is None:
        row = Cfdi(kind=kind, period=period, refuge_id=refuge_id, status="pending_pac")
        db.add(row)
    if row.status != "issued":  # lo timbrado no se toca
        for key, value in amounts.items():
            setattr(row, key, value)
    return row


def generate_period_cfdis(db: Session, period: str | None = None, adapter: PacAdapter | None = None) -> dict:
    """Crea (o actualiza si no se han timbrado) los CFDI del periodo y los timbra si hay PAC.

    Los montos ya vienen netos de los reembolsos hechos en el mes (statements.refuge_statement). Si en un mes los
    reembolsos superan a las ventas (comisión o retención negativa) no se emite CFDI de ingreso: lo que procede
    es un CFDI de egreso relacionado con el del mes original; se cuenta en credit_notes_needed para el contador.
    """
    period = period or previous_period()
    from app.services.statements import admin_statements

    summary = admin_statements(db, period)
    result = {"period": period, "created": 0, "issued": 0, "pending_pac": 0, "errors": 0, "credit_notes_needed": 0}
    rows: list[tuple[Cfdi, dict]] = []
    for st in summary["refuges"]:
        if not has_activity(st):
            continue
        fee = Decimal(st["platform_fee"]) + Decimal(st["donations_fee"])
        if fee > 0:
            subtotal, iva, total = commission_amounts(fee)
            rows.append((_upsert(db, "comision", period, st["refuge_id"],
                                 {"subtotal": subtotal, "iva": iva, "total": total}), st))
        retained = Decimal(st["isr_retenido"]) + Decimal(st["iva_retenido"])
        if retained > 0:
            rows.append((_upsert(db, "retencion", period, st["refuge_id"],
                                 {"subtotal": Decimal(st.get("net_sales", st["gross"])),
                                  "isr_retenido": st["isr_retenido"], "iva_retenido": st["iva_retenido"],
                                  "total": retained}), st))
        if fee < 0 or retained < 0:
            result["credit_notes_needed"] += 1
            logger.warning("Refugio %s: en %s los reembolsos superan a las ventas; emite el CFDI de egreso",
                           st["refuge_id"], period)
    db.commit()
    result["created"] = len(rows)
    adapter = adapter or get_adapter()
    for row, st in rows:
        issue_cfdi_row(db, row, adapter=adapter, statement=st)
        result[{"issued": "issued", "pending_pac": "pending_pac"}.get(row.status, "errors")] += 1
    if rows:
        logger.info("CFDI del periodo %s: %s", period, result)
    return result
