import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Tuple, Union

import requests
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.tipo_cambio import TipoCambio
from app.models.worker_job_state import WorkerJobState
from app.services import wabot_client
from app.services.sell_in import bonos_costo
from app.services.sell_out import queue as sell_out_queue

logger = logging.getLogger(__name__)

# `worker_job_state` row that counts consecutive failed BNA fetches (any caller: cron script, sync endpoint,
# sync_completo). After FALLAS_PARA_ALERTAR in a row (30 min at the */5 cron) the owner gets ONE WhatsApp.
ESTADO_JOB = "tipo_cambio.bna"
FALLAS_PARA_ALERTAR = 6


def actualizar_tipo_cambio_bna(db: Session) -> dict:
    """Obtiene tipo de cambio USD BILLETE (venta) desde BNA.

    Fuente: tabla "Billetes" de https://www.bna.com.ar/Personas (tab id=billetes).
    NO usar la tabla "Divisas / Mercado Libre de Cambios" de la misma página:
    esa es otra cotización (menor, con fecha de último cierre) y no es la que
    alimenta el pricing. Se ancla la fila por el texto "Dolar U.S.A" tomando la
    primera coincidencia en orden de documento (= tabla Billetes del día).
    """
    # The fetch alone runs inside the `try`; the failure is counted and alerted ONCE, outside it, so bookkeeping
    # that fails can never be caught here and counted (and alerted) a second time.
    try:
        cotizacion = _obtener_cotizacion_bna(db)
    except Exception as e:  # noqa: BLE001 -- any failure (import, network, parse, DB) must be counted and alerted
        # Session contract: callers pass a dedicated session with nothing pending (sync endpoint, sync scripts),
        # so rolling back discards only this update and never leaves the session in a failed transaction.
        db.rollback()
        return _registrar_falla(db, str(e))
    if isinstance(cotizacion, str):
        return _registrar_falla(db, cotizacion)
    compra, venta = cotizacion
    _registrar_estado(db, fallas=0, alertado=False, ultimo_error=None)
    return {"status": "success", "compra": compra, "venta": venta, "fuente": "BNA"}


def _obtener_cotizacion_bna(db: Session) -> Union[Tuple[float, float], str]:
    """Scrape the BNA Billetes row and store it (`guardar_cotizacion_bna`). Returns `(compra, venta)`, or the
    error message when the page has no usable row; raises on import, network or DB errors."""
    # Imported here so a missing parser is a counted, alerted failure (it stopped the rate on 2026-11-06)
    # instead of an ImportError that takes down every caller of this module.
    from lxml import html

    # El BNA carga las cotizaciones vía POST al tab de billetes y exige
    # User-Agent (un GET plano devuelve un HTML sin las tablas).
    url = "https://www.bna.com.ar/Personas?id=billetes"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    response = requests.post(url, timeout=10, headers=headers)
    tree = html.fromstring(response.content)

    # Primera fila "Dolar U.S.A" en el documento = tabla Billetes (compra, venta).
    filas = tree.xpath("//tr[td[contains(normalize-space(.), 'Dolar U.S.A')]]")
    if not filas:
        return "No se encontraron valores en BNA"

    celdas = [c.strip() for c in filas[0].xpath("./td//text()") if c.strip()]
    if len(celdas) < 3:
        return "Fila de dólar incompleta en BNA"

    # Limpiar y convertir: 1450,00 -> 1450.0
    compra = float(celdas[1].replace(".", "").replace(",", "."))
    venta = float(celdas[2].replace(".", "").replace(",", "."))

    if compra == 0 or venta == 0:
        return "Valores inválidos"

    guardar_cotizacion_bna(db, compra, venta)
    return compra, venta


def _registrar_falla(db: Session, mensaje: str) -> Dict[str, Any]:
    """Log the failed fetch as ERROR, count it, and alert the owner once at FALLAS_PARA_ALERTAR in a row (an alert
    wabot did not take, or that raised, is retried on the next failure). Never raises: returns the error result."""
    logger.error("BNA: no se pudo actualizar el tipo de cambio USD: %s", mensaje)
    estado = _leer_estado(db)
    fallas = int(estado.get("fallas_consecutivas", 0)) + 1
    alertado = bool(estado.get("alertado", False))
    if fallas >= FALLAS_PARA_ALERTAR and not alertado:
        alertado = _avisar_owner(
            f"Pricing: el tipo de cambio USD no se actualiza ({fallas} intentos seguidos fallaron). "
            f"Último error: {mensaje}"
        )
    _registrar_estado(db, fallas=fallas, alertado=alertado, ultimo_error=mensaje)
    return {"status": "error", "message": mensaje}


def _avisar_owner(mensaje: str) -> bool:
    """Send the WhatsApp; True only when wabot took it. An alert must never break the run that sends it, so any
    exception from the client is logged and counts as not sent."""
    try:
        envio = wabot_client.send_to_owner(mensaje)
    except Exception:  # noqa: BLE001 -- whatever the client raises, the rate update must finish
        logger.exception("BNA: no se pudo avisar al owner por wabot")
        return False
    if envio != "sent":
        logger.error("BNA: no se pudo avisar al owner por wabot (%s)", envio)
        return False
    return True


def _leer_estado(db: Session) -> Dict[str, Any]:
    try:
        detail = db.query(WorkerJobState.detail).filter(WorkerJobState.name == ESTADO_JOB).scalar()
    except SQLAlchemyError:
        logger.exception("BNA: no se pudo leer el estado de fallas")
        db.rollback()
        return {}
    return dict(detail or {})


def _registrar_estado(db: Session, *, fallas: int, alertado: bool, ultimo_error: str | None) -> None:
    """Persist the failure count. Observability never fails the update: a write error is logged and dropped."""
    ahora = datetime.now(timezone.utc)
    try:
        row = db.get(WorkerJobState, ESTADO_JOB)
        if row is None:
            row = WorkerJobState(name=ESTADO_JOB)
            db.add(row)
        row.last_run_at = ahora
        if fallas == 0:
            row.last_success_at = ahora
        row.detail = {"fallas_consecutivas": fallas, "alertado": alertado, "ultimo_error": ultimo_error}
        db.commit()
    except SQLAlchemyError:
        logger.exception("BNA: no se pudo guardar el estado de fallas")
        db.rollback()


def guardar_cotizacion_bna(db: Session, compra: float, venta: float) -> None:
    """Guarda la cotización USD de hoy y, si `venta` cambió, encola en la misma transacción las
    campañas de sell out que se mueven con el BNA (`sell_out.queue.enqueue_por_bna`) y los bonos de
    costo de sell in en USD (`bonos_costo.encolar_por_bna`: al cobro sin tipo de cambio del cobro y día
    de venta vigentes), cada uno en su savepoint: si encolar falla se loguea y la cotización se guarda
    igual. Commitea."""
    hoy = date.today()
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == hoy).first()
    cambio = tc is None or float(tc.venta or 0) != venta
    if tc:
        tc.compra = compra
        tc.venta = venta
    else:
        db.add(TipoCambio(moneda="USD", fecha=hoy, compra=compra, venta=venta))
    if cambio:
        db.flush()
        try:
            with db.begin_nested():  # the rate is stored even if queueing fails
                sell_out_queue.enqueue_por_bna(db, hoy)
        except Exception:
            logger.exception("BNA: no se pudieron encolar las campañas de sell-out; el tipo de cambio se guarda igual")
        try:
            with db.begin_nested():
                bonos_costo.encolar_por_bna(db, hoy)
        except Exception:
            logger.exception(
                "BNA: no se pudieron encolar los bonos de sell-in en USD; el tipo de cambio se guarda igual"
            )
    db.commit()
