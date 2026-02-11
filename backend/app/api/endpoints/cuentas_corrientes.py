"""
Endpoints para informes de cuentas corrientes (proveedores y clientes).
- Proveedores: export 26 del ERP
- Clientes: export 29 del ERP
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import httpx

from app.core.database import get_db
from app.core.exceptions import api_error, ErrorCode
from app.core.logging import get_logger
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.cuenta_corriente_proveedor import CuentaCorrienteProveedor
from app.models.cuenta_corriente_cliente import CuentaCorrienteCliente

router = APIRouter()
logger = get_logger(__name__)

# URL interna del gbp-parser (mismo servidor)
GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"


def _parse_decimal(value: str) -> float:
    """Convierte string a float, tolerando vacíos y formatos raros del ERP."""
    if not value or not str(value).strip():
        return 0.0
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return 0.0


async def _fetch_from_erp(export_id: int) -> list[dict]:
    """Obtiene datos del ERP llamando al gbp-parser con el export indicado."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(GBP_PARSER_URL, params={"intExpgr_id": export_id})

    if response.status_code != 200:
        raise api_error(
            502,
            ErrorCode.INTERNAL_ERROR,
            f"Error del gbp-parser: {response.status_code} - {response.text[:200]}",
        )

    data = response.json()

    if not isinstance(data, list):
        raise api_error(502, ErrorCode.INTERNAL_ERROR, "Respuesta inesperada del ERP")

    return data


# ---------------------------------------------------------------------------
# Proveedores (export 26)
# ---------------------------------------------------------------------------


@router.get("/cuentas-corrientes/proveedores")
async def listar_cuentas_corrientes_proveedores(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
    buscar: Optional[str] = Query(None, description="Buscar por nombre de proveedor"),
) -> dict:
    """
    Cuentas corrientes de proveedores (truncate-and-reload desde export 26).
    """
    try:
        rows = await _fetch_from_erp(26)

        db.query(CuentaCorrienteProveedor).delete()
        db.flush()

        registros = []
        for row in rows:
            registros.append(
                CuentaCorrienteProveedor(
                    bra_id=int(row.get("BraID", 0) or 0),
                    id_proveedor=int(row.get("ID_Proveedor", 0) or 0),
                    proveedor=str(row.get("Proveedor", "")).strip(),
                    monto_total=_parse_decimal(row.get("Monto_Total", "0")),
                    monto_abonado=_parse_decimal(row.get("Monto_Abonado", "0")),
                    pendiente=_parse_decimal(row.get("Pendiente", "0")),
                )
            )

        db.bulk_save_objects(registros)
        db.commit()
        logger.info("CC proveedores sincronizadas: %d registros", len(registros))

    except Exception as e:
        db.rollback()
        logger.error("Error sincronizando CC proveedores: %s", e, exc_info=True)

        if db.query(CuentaCorrienteProveedor).count() == 0:
            raise api_error(
                502,
                ErrorCode.INTERNAL_ERROR,
                f"Error al consultar ERP y no hay datos previos: {str(e)}",
            )
        logger.warning("Devolviendo datos previos de CC proveedores")

    query = db.query(CuentaCorrienteProveedor)
    if buscar:
        query = query.filter(CuentaCorrienteProveedor.proveedor.ilike(f"%{buscar}%"))
    query = query.order_by(CuentaCorrienteProveedor.proveedor)
    resultados = query.all()

    return {
        "total": len(resultados),
        "data": [
            {
                "id": r.id,
                "bra_id": r.bra_id,
                "id_proveedor": r.id_proveedor,
                "proveedor": r.proveedor,
                "monto_total": float(r.monto_total) if r.monto_total else 0,
                "monto_abonado": float(r.monto_abonado) if r.monto_abonado else 0,
                "pendiente": float(r.pendiente) if r.pendiente else 0,
            }
            for r in resultados
        ],
    }


# ---------------------------------------------------------------------------
# Clientes (export 29)
# ---------------------------------------------------------------------------


@router.get("/cuentas-corrientes/clientes")
async def listar_cuentas_corrientes_clientes(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
    buscar: Optional[str] = Query(None, description="Buscar por nombre de cliente"),
) -> dict:
    """
    Cuentas corrientes de clientes (truncate-and-reload desde export 29).
    """
    try:
        rows = await _fetch_from_erp(29)

        db.query(CuentaCorrienteCliente).delete()
        db.flush()

        registros = []
        for row in rows:
            registros.append(
                CuentaCorrienteCliente(
                    bra_id=int(row.get("BraID", 0) or 0),
                    id_cliente=int(row.get("ID_Cliente", 0) or 0),
                    cliente=str(row.get("Cliente", "")).strip(),
                    monto_total=_parse_decimal(row.get("Monto_Total", "0")),
                    monto_abonado=_parse_decimal(row.get("Monto_Abonado", "0")),
                    pendiente=_parse_decimal(row.get("Pendiente", "0")),
                )
            )

        db.bulk_save_objects(registros)
        db.commit()
        logger.info("CC clientes sincronizadas: %d registros", len(registros))

    except Exception as e:
        db.rollback()
        logger.error("Error sincronizando CC clientes: %s", e, exc_info=True)

        if db.query(CuentaCorrienteCliente).count() == 0:
            raise api_error(
                502,
                ErrorCode.INTERNAL_ERROR,
                f"Error al consultar ERP y no hay datos previos: {str(e)}",
            )
        logger.warning("Devolviendo datos previos de CC clientes")

    query = db.query(CuentaCorrienteCliente)
    if buscar:
        query = query.filter(CuentaCorrienteCliente.cliente.ilike(f"%{buscar}%"))
    query = query.order_by(CuentaCorrienteCliente.cliente)
    resultados = query.all()

    return {
        "total": len(resultados),
        "data": [
            {
                "id": r.id,
                "bra_id": r.bra_id,
                "id_cliente": r.id_cliente,
                "cliente": r.cliente,
                "monto_total": float(r.monto_total) if r.monto_total else 0,
                "monto_abonado": float(r.monto_abonado) if r.monto_abonado else 0,
                "pendiente": float(r.pendiente) if r.pendiente else 0,
            }
            for r in resultados
        ],
    }
