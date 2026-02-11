"""
Endpoints para informes de cuentas corrientes (proveedores y clientes).
- Proveedores: export 26 del ERP
- Clientes: export 29 del ERP
"""

from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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
from app.models.tb_branch import TBBranch

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


def _build_branch_map(db: Session) -> dict[int, str]:
    """Construye un diccionario bra_id -> bra_desc de sucursales activas."""
    branches = (
        db.query(TBBranch.bra_id, TBBranch.bra_desc)
        .filter(TBBranch.bra_disabled == False)  # noqa: E712
        .all()
    )
    return {b.bra_id: b.bra_desc or f"Sucursal {b.bra_id}" for b in branches}


# ---------------------------------------------------------------------------
# Sucursales disponibles (para el filtro del frontend)
# ---------------------------------------------------------------------------


@router.get("/cuentas-corrientes/sucursales")
async def listar_sucursales_cc(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> list[dict]:
    """
    Retorna las sucursales activas para el filtro de cuentas corrientes.
    """
    sucursales = (
        db.query(TBBranch.bra_id, TBBranch.bra_desc)
        .filter(TBBranch.bra_disabled == False)  # noqa: E712
        .order_by(TBBranch.bra_desc)
        .all()
    )
    return [{"bra_id": s.bra_id, "bra_desc": s.bra_desc} for s in sucursales]


# ---------------------------------------------------------------------------
# Proveedores (export 26)
# ---------------------------------------------------------------------------


@router.get("/cuentas-corrientes/proveedores")
async def listar_cuentas_corrientes_proveedores(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
    buscar: Optional[str] = Query(None, description="Buscar por nombre de proveedor"),
    sucursal: Optional[int] = Query(None, description="Filtrar por bra_id de sucursal"),
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

    branch_map = _build_branch_map(db)

    query = db.query(CuentaCorrienteProveedor)
    if buscar:
        query = query.filter(CuentaCorrienteProveedor.proveedor.ilike(f"%{buscar}%"))
    if sucursal is not None:
        query = query.filter(CuentaCorrienteProveedor.bra_id == sucursal)
    query = query.order_by(CuentaCorrienteProveedor.proveedor)
    resultados = query.all()

    return {
        "total": len(resultados),
        "data": [
            {
                "id": r.id,
                "bra_id": r.bra_id,
                "sucursal": branch_map.get(r.bra_id, f"Sucursal {r.bra_id}"),
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
    sucursal: Optional[int] = Query(None, description="Filtrar por bra_id de sucursal"),
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

    branch_map = _build_branch_map(db)

    query = db.query(CuentaCorrienteCliente)
    if buscar:
        query = query.filter(CuentaCorrienteCliente.cliente.ilike(f"%{buscar}%"))
    if sucursal is not None:
        query = query.filter(CuentaCorrienteCliente.bra_id == sucursal)
    query = query.order_by(CuentaCorrienteCliente.cliente)
    resultados = query.all()

    return {
        "total": len(resultados),
        "data": [
            {
                "id": r.id,
                "bra_id": r.bra_id,
                "sucursal": branch_map.get(r.bra_id, f"Sucursal {r.bra_id}"),
                "id_cliente": r.id_cliente,
                "cliente": r.cliente,
                "monto_total": float(r.monto_total) if r.monto_total else 0,
                "monto_abonado": float(r.monto_abonado) if r.monto_abonado else 0,
                "pendiente": float(r.pendiente) if r.pendiente else 0,
            }
            for r in resultados
        ],
    }


# ---------------------------------------------------------------------------
# Exportar XLSX (proveedores o clientes, con filtros aplicados)
# ---------------------------------------------------------------------------


@router.get("/cuentas-corrientes/exportar")
async def exportar_cuentas_corrientes(
    tipo: str = Query(..., description="'proveedores' o 'clientes'"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
    buscar: Optional[str] = Query(None, description="Buscar por nombre"),
    sucursal: Optional[int] = Query(None, description="Filtrar por bra_id"),
) -> StreamingResponse:
    """
    Exporta las cuentas corrientes (con filtros aplicados) a un archivo XLSX.
    No sincroniza con ERP — usa los datos ya cacheados en la tabla.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill

    if tipo not in ("proveedores", "clientes"):
        raise api_error(422, ErrorCode.VALIDATION_ERROR, "tipo debe ser 'proveedores' o 'clientes'")

    branch_map = _build_branch_map(db)

    # Elegir modelo y campos según tipo
    if tipo == "proveedores":
        model = CuentaCorrienteProveedor
        name_field = model.proveedor
        id_field_label = "ID Proveedor"
        name_label = "Proveedor"
    else:
        model = CuentaCorrienteCliente
        name_field = model.cliente
        id_field_label = "ID Cliente"
        name_label = "Cliente"

    query = db.query(model)
    if buscar:
        query = query.filter(name_field.ilike(f"%{buscar}%"))
    if sucursal is not None:
        query = query.filter(model.bra_id == sucursal)
    query = query.order_by(name_field)
    resultados = query.all()

    # Crear workbook
    wb = Workbook()
    ws = wb.active
    ws.title = f"CC {tipo.capitalize()}"

    # Estilos
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    money_fmt = "#,##0.00"

    # Headers
    headers = ["Sucursal", id_field_label, name_label, "Monto Total", "Abonado", "Pendiente"]
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align

    # Data
    for row_idx, r in enumerate(resultados, 2):
        sucursal_nombre = branch_map.get(r.bra_id, f"Sucursal {r.bra_id}")
        id_valor = r.id_proveedor if tipo == "proveedores" else r.id_cliente
        nombre_valor = r.proveedor if tipo == "proveedores" else r.cliente

        ws.cell(row=row_idx, column=1, value=sucursal_nombre)
        ws.cell(row=row_idx, column=2, value=id_valor)
        ws.cell(row=row_idx, column=3, value=nombre_valor)

        cell_total = ws.cell(row=row_idx, column=4, value=float(r.monto_total or 0))
        cell_total.number_format = money_fmt

        cell_abonado = ws.cell(row=row_idx, column=5, value=float(r.monto_abonado or 0))
        cell_abonado.number_format = money_fmt

        cell_pendiente = ws.cell(row=row_idx, column=6, value=float(r.pendiente or 0))
        cell_pendiente.number_format = money_fmt

    # Fila de totales
    total_row = len(resultados) + 2
    ws.cell(row=total_row, column=3, value="TOTALES").font = Font(bold=True)

    for col_idx in (4, 5, 6):
        col_letter = chr(64 + col_idx)  # D, E, F
        cell = ws.cell(
            row=total_row,
            column=col_idx,
            value=f"=SUM({col_letter}2:{col_letter}{total_row - 1})",
        )
        cell.number_format = money_fmt
        cell.font = Font(bold=True)

    # Autofit columns (approximation)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 40
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 16
    ws.column_dimensions["F"].width = 16

    # Escribir a buffer
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"cuentas_corrientes_{tipo}_{timestamp}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
