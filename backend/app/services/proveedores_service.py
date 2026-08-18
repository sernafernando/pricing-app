"""
ProveedoresService — lógica de negocio para proveedores centralizados.

Responsabilidades:
  - CRUD de proveedores
  - Sync desde ERP: cadena completa GBP → tb_supplier → proveedores
  - Creación y vinculación de rma_proveedores
  - Consulta AFIP y persistencia de datos fiscales
"""

from datetime import UTC, datetime
from typing import Any, Optional

import httpx
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload
from starlette.concurrency import run_in_threadpool

from app.core.logging import get_logger
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.proveedor_datos_fiscales import ProveedorDatosFiscales
from app.models.rma_proveedor import RmaProveedor
from app.models.tb_supplier import TBSupplier
from app.services.afip_service import AfipService, AfipServiceError

logger = get_logger(__name__)

# Campos que viajan a tb_supplier (el resto de la fila del ERP se descarta).
# Es una tupla y no un set para que el orden de las claves del dict normalizado
# sea determinístico entre corridas.
SUPPLIER_VALID_FIELDS = ("comp_id", "supp_id", "supp_name", "supp_tax_number")

# Campos que el ERP expone con otro nombre
SUPPLIER_FIELD_MAP = {
    "supp_taxNumber": "supp_tax_number",
}


class ErpSyncError(Exception):
    """El ERP (gbp-parser) no devolvió datos utilizables para sincronizar."""


def is_erp_error(data: list[Any]) -> bool:
    """
    Detecta respuestas de error del ERP (ej: [{"Column1": "-9"}]).

    El gbp-parser devuelve HTTP 200 incluso cuando el script falla, así que
    la única forma de detectarlo es por la forma del payload.
    """
    if len(data) == 1 and isinstance(data[0], dict):
        first = data[0]
        if "Column1" in first:
            try:
                return int(first["Column1"]) < 0
            except (ValueError, TypeError):
                return False
        if not any(field in first for field in {"comp_id", "supp_id", "supp_name"}):
            return True
    return False


def normalize_supplier_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Normaliza y filtra una fila de proveedor del ERP.

    Renombra los campos según SUPPLIER_FIELD_MAP y descarta las filas que no
    son utilizables:

      - Sin clave ERP (comp_id / supp_id). El chequeo es explícito contra
        None: comp_id = 0 es una clave válida y no debe descartarse.
      - Con clave ERP no casteable a entero. El gbp-parser puede devolver
        "11" (string) en lugar de 11; sin castear, la clave del payload no
        matchea contra la de los objetos ORM (ints) y se daría de alta un
        proveedor duplicado en lugar de actualizar el existente.
      - Sin `supp_name` utilizable. `tb_supplier.supp_name`,
        `proveedores.nombre` y `rma_proveedores.nombre` son NOT NULL: una
        sola fila sin nombre revienta la transacción completa y deja el sync
        en cero.

    Retorna None si la fila no es utilizable.
    """
    row = dict(row)

    for erp_name, local_name in SUPPLIER_FIELD_MAP.items():
        if erp_name in row:
            row[local_name] = row.pop(erp_name)

    for campo in ("comp_id", "supp_id"):
        valor = row.get(campo)
        if valor is None:
            return None
        try:
            row[campo] = int(valor)
        except (ValueError, TypeError):
            return None

    nombre = row.get("supp_name")
    if nombre is None or not str(nombre).strip():
        return None

    # Todas las filas salen con EXACTAMENTE las mismas claves. `execute(stmt, lista)`
    # compila el executemany a partir del primer dict: si el ERP omite
    # `supp_taxNumber` en algunas filas y no en otras, los dicts quedan
    # heterogéneos y revienta el insert completo. Se completa con None en lugar
    # de omitir la clave.
    return {campo: row.get(campo) for campo in SUPPLIER_VALID_FIELDS}


class ProveedoresService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # =====================================================================
    # QUERIES
    # =====================================================================

    def listar(
        self,
        search: Optional[str] = None,
        solo_activos: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Proveedor], int]:
        """Lista proveedores con búsqueda, filtro y paginación."""
        query = self.db.query(Proveedor).options(
            joinedload(Proveedor.datos_fiscales),
        )

        if solo_activos:
            query = query.filter(Proveedor.activo == True)  # noqa: E712

        if search:
            import re

            like = f"%{search}%"
            # Normalized search: strip non-alphanumeric for acronym matching
            norm_term = re.sub(r"[^a-zA-Z0-9]", "", search).lower()
            strip_re = "[^a-zA-Z0-9]"
            norm_nombre = sa_func.lower(sa_func.regexp_replace(Proveedor.nombre, strip_re, "", "g"))

            query = query.filter(
                norm_nombre.like(f"%{norm_term}%")
                | Proveedor.nombre.ilike(like)
                | Proveedor.cuit.ilike(like)
                | Proveedor.ciudad.ilike(like)
            )

        total = query.count()
        proveedores = query.order_by(Proveedor.nombre).offset((page - 1) * page_size).limit(page_size).all()

        return proveedores, total

    def obtener(self, proveedor_id: int) -> Optional[Proveedor]:
        """Obtiene un proveedor por ID con todas las sub-entidades."""
        return (
            self.db.query(Proveedor)
            .options(
                joinedload(Proveedor.datos_fiscales),
                joinedload(Proveedor.direcciones),
                joinedload(Proveedor.bancos),
                joinedload(Proveedor.contactos),
            )
            .filter(Proveedor.id == proveedor_id)
            .first()
        )

    def obtener_por_cuit(self, cuit: str) -> Optional[Proveedor]:
        """Obtiene un proveedor por CUIT."""
        return self.db.query(Proveedor).filter(Proveedor.cuit == cuit).first()

    # =====================================================================
    # CRUD
    # =====================================================================

    def crear(
        self,
        nombre: str,
        cuit: Optional[str] = None,
        origen: str = OrigenProveedor.MANUAL,
        **kwargs: Any,
    ) -> Proveedor:
        """Crea un proveedor manualmente."""
        proveedor = Proveedor(
            nombre=nombre,
            cuit=cuit,
            origen=origen,
            **kwargs,
        )
        self.db.add(proveedor)
        self.db.flush()
        return proveedor

    def actualizar(self, proveedor_id: int, data: dict[str, Any]) -> Optional[Proveedor]:
        """Actualiza campos de un proveedor."""
        prov = self.db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
        if not prov:
            return None

        for field, value in data.items():
            if hasattr(prov, field):
                setattr(prov, field, value)

        self.db.flush()
        return prov

    # =====================================================================
    # SYNC DESDE ERP
    # =====================================================================

    async def sync_desde_erp(self, supp_id: Optional[int] = None) -> dict[str, int]:
        """
        Cadena canónica de sincronización de proveedores. Punto de entrada único
        tanto para el cron (`app.scripts.sync_suppliers`) como para el botón
        "Sincronizar con ERP" del panel de Administración.

        Pasos:
          1. Consulta el ERP (GBP) vía `erp_worker_client` (I/O async) y
             normaliza las filas recibidas.
          2. Upsert de las filas recibidas en el mirror local `tb_supplier`.
          3. Proyección a la tabla central `proveedores`: alta de los nuevos y
             actualización de nombre/CUIT en los existentes (nunca pisa datos
             extendidos cargados a mano).
          4. Alta de los `rma_proveedores` faltantes y vinculación de los que
             ya existían sin `proveedor_id`.

        Los pasos 2/3/4 viven en `_persistir_sync`, un método sincrónico que se
        ejecuta en un worker thread vía `run_in_threadpool`. La sesión que usa
        el servicio es sincrónica (`SessionLocal`, ver `app/core/database.py`):
        correr el upsert masivo, los dos `query(...).all()`, los `flush()` por
        proveedor nuevo y el commit directamente en la corrutina bloquearía el
        event loop y congelaría la API entera durante todo el sync.

        Args:
            supp_id: si se indica, sincroniza solo ese proveedor del ERP.

        Returns:
            Contadores: {insertados, actualizados, vinculados_rma,
                         rma_insertados, total_erp}. `total_erp` es la cantidad
            real de filas devueltas por el ERP, no el tamaño del mirror local.

        Raises:
            ErpSyncError: si el ERP no responde, devuelve vacío o devuelve una
                respuesta con forma de error. Nunca se retornan contadores en
                cero ante un fetch fallido: eso hacía que un cron o el botón
                mostraran éxito sin haber sincronizado nada.
        """
        # ponytail: `app/routers/rma_proveedores.py:181` y
        # `app/api/endpoints/erp_sync.py:407` todavía tienen su propia copia del
        # loop de proyección de tb_supplier. Deberían delegar en esta función
        # canónica; se dejó fuera de alcance en el fix del cron + botón.

        # ── Paso 1: traer del ERP (falla fuerte) ──────────────────────────
        from app.services.erp_worker_client import erp_worker_client

        try:
            suppliers = await erp_worker_client.get_suppliers(supp_id=supp_id)
        except (httpx.HTTPError, ValueError) as e:
            raise ErpSyncError(f"No se pudo consultar el ERP (gbp-parser): {e}") from e

        if not isinstance(suppliers, list) or not suppliers:
            raise ErpSyncError("El ERP no devolvió proveedores (respuesta vacía o con formato inesperado)")

        if is_erp_error(suppliers):
            raise ErpSyncError(f"El ERP devolvió una respuesta de error: {suppliers[0]}")

        normalized: list[dict[str, Any]] = []
        descartados = 0
        for row in suppliers:
            if not isinstance(row, dict):
                descartados += 1
                continue
            norm = normalize_supplier_row(row)
            if norm is None:
                descartados += 1
                continue
            normalized.append(norm)

        if not normalized:
            raise ErpSyncError(
                f"El ERP devolvió {len(suppliers)} filas pero ninguna tiene comp_id/supp_id/supp_name utilizables"
            )

        if descartados:
            logger.warning(
                "Sync proveedores ERP: %d filas descartadas por comp_id/supp_id/supp_name inválidos",
                descartados,
            )

        # ── Pasos 2, 3 y 4: persistencia (bloqueante) fuera del event loop ──
        return await run_in_threadpool(self._persistir_sync, normalized, len(suppliers))

    def _persistir_sync(self, normalized: list[dict[str, Any]], total_erp: int) -> dict[str, int]:
        """
        Persiste el resultado del fetch al ERP: mirror `tb_supplier`, proyección
        a `proveedores` y alta/vinculación de `rma_proveedores`.

        Método sincrónico a propósito: lo llama `sync_desde_erp` vía
        `run_in_threadpool` para no bloquear el event loop de FastAPI. Toda la
        operación va en una única transacción; ante cualquier error se hace
        rollback y se re-lanza (no se dejan sesiones sucias).

        Args:
            normalized: filas ya normalizadas por `normalize_supplier_row`.
            total_erp: cantidad de filas que devolvió el ERP (incluye las
                descartadas), para reportarla tal cual en los contadores.

        Returns:
            Contadores: {insertados, actualizados, vinculados_rma,
                         rma_insertados, total_erp}.
        """
        try:
            # ── Paso 2: upsert del mirror tb_supplier ─────────────────────
            stmt = pg_insert(TBSupplier)
            stmt = stmt.on_conflict_do_update(
                index_elements=["comp_id", "supp_id"],
                set_={
                    "supp_name": stmt.excluded.supp_name,
                    "supp_tax_number": stmt.excluded.supp_tax_number,
                },
            )
            self.db.execute(stmt, normalized)

            # ── Pasos 3 y 4: proyección a proveedores + rma_proveedores ───
            # Index proveedores existentes por (comp_id, supp_id)
            existing: dict[tuple[int, int], Proveedor] = {
                (p.comp_id, p.supp_id): p for p in self.db.query(Proveedor).filter(Proveedor.supp_id.isnot(None)).all()
            }

            # Index de rma_proveedores: por clave ERP y por proveedor ya vinculado
            # (proveedor_id es UNIQUE, no se puede crear un segundo rma para el mismo proveedor)
            rma_rows = self.db.query(RmaProveedor).all()
            rma_por_supp: dict[tuple[int, int], RmaProveedor] = {
                (r.comp_id, r.supp_id): r for r in rma_rows if r.supp_id is not None
            }
            rma_vinculados_ids: set[int] = {r.proveedor_id for r in rma_rows if r.proveedor_id is not None}

            insertados = 0
            actualizados = 0
            vinculados_rma = 0
            rma_insertados = 0

            for supp in normalized:
                key = (supp["comp_id"], supp["supp_id"])
                nombre = supp.get("supp_name")
                cuit = supp.get("supp_tax_number")

                if key in existing:
                    prov = existing[key]
                    # Solo actualizar nombre y CUIT (no pisar datos extendidos)
                    changed = False
                    if prov.nombre != nombre:
                        prov.nombre = nombre
                        changed = True
                    if prov.cuit != cuit:
                        prov.cuit = cuit
                        changed = True
                    if changed:
                        actualizados += 1
                else:
                    prov = Proveedor(
                        supp_id=supp["supp_id"],
                        comp_id=supp["comp_id"],
                        nombre=nombre,
                        cuit=cuit,
                        origen=OrigenProveedor.ERP,
                    )
                    self.db.add(prov)
                    self.db.flush()  # para obtener prov.id
                    existing[key] = prov
                    insertados += 1

                rma = rma_por_supp.get(key)
                if rma is not None:
                    # Vincular rma_proveedor existente que quedó suelto
                    if rma.proveedor_id is None:
                        rma.proveedor_id = prov.id
                        rma_vinculados_ids.add(prov.id)
                        vinculados_rma += 1
                elif prov.id not in rma_vinculados_ids:
                    # Proveedor nuevo del ERP: todavía no tiene fila en RMA.
                    # ponytail: `rma_proveedores.supp_id` tiene un UNIQUE simple
                    # (`rma_proveedores_supp_id_key`), no compuesto con comp_id.
                    # Hoy no molesta porque tb_supplier solo tiene comp_id=1, pero
                    # si alguna vez entra una segunda empresa con supp_id repetido
                    # este insert viola la constraint. Corresponde migrar ese índice
                    # a UNIQUE(comp_id, supp_id) igual que en tb_supplier.
                    self.db.add(
                        RmaProveedor(
                            proveedor_id=prov.id,
                            supp_id=supp["supp_id"],
                            comp_id=supp["comp_id"],
                            nombre=nombre,
                            cuit=cuit,
                        )
                    )
                    rma_vinculados_ids.add(prov.id)
                    rma_insertados += 1

            self.db.commit()
        except Exception:
            # Amplio a propósito: un IntegrityError entra por SQLAlchemyError,
            # pero cualquier otro error dentro del loop (ej. AttributeError)
            # dejaría la sesión sucia si no se hiciera rollback acá.
            self.db.rollback()
            raise

        logger.info(
            "Sync proveedores ERP: insertados=%d, actualizados=%d, vinculados_rma=%d, rma_insertados=%d, total_erp=%d",
            insertados,
            actualizados,
            vinculados_rma,
            rma_insertados,
            total_erp,
        )

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "vinculados_rma": vinculados_rma,
            "rma_insertados": rma_insertados,
            "total_erp": total_erp,
        }

    # =====================================================================
    # CONSULTA AFIP
    # =====================================================================

    async def consultar_afip(self, proveedor_id: int) -> ProveedorDatosFiscales:
        """
        Consulta AFIP Padrón A4 para un proveedor y persiste los datos fiscales.

        Si el proveedor no tiene CUIT, levanta ValueError.
        Si AFIP falla, guarda el error en ultimo_error_afip.
        """
        prov = self.db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
        if not prov:
            raise ValueError(f"Proveedor {proveedor_id} no encontrado")

        if not prov.cuit:
            raise ValueError(f"Proveedor '{prov.nombre}' no tiene CUIT cargado")

        # Obtener o crear el registro de datos fiscales
        datos = (
            self.db.query(ProveedorDatosFiscales).filter(ProveedorDatosFiscales.proveedor_id == proveedor_id).first()
        )
        if not datos:
            datos = ProveedorDatosFiscales(proveedor_id=proveedor_id)
            self.db.add(datos)

        try:
            afip = AfipService()
            persona, wsid = await afip.get_persona(prov.cuit)

            # Extraer campos derivados y guardar
            campos = AfipService.build_datos_fiscales_from_persona(persona, prov.cuit, wsid)
            for field, value in campos.items():
                setattr(datos, field, value)

            self.db.commit()
            self.db.refresh(datos)

            logger.info(
                "AFIP consultado OK para proveedor=%d, cuit=%s, wsid=%s, condicion_iva=%s",
                proveedor_id,
                prov.cuit,
                wsid,
                datos.condicion_iva,
            )

        except AfipServiceError as e:
            # Guardar el error pero no romper
            datos.ultimo_error_afip = f"{e.message}: {e.detail}"
            datos.ultima_consulta_afip = datetime.now(UTC)
            datos.cuit_consultado = prov.cuit
            self.db.commit()
            self.db.refresh(datos)
            logger.error(
                "Error AFIP para proveedor=%d, cuit=%s: %s",
                proveedor_id,
                prov.cuit,
                e.message,
            )
            raise

        return datos
