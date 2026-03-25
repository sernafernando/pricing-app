"""
ProveedoresService — lógica de negocio para proveedores centralizados.

Responsabilidades:
  - CRUD de proveedores
  - Sync desde ERP (tb_supplier → proveedores)
  - Vinculación con rma_proveedores existentes
  - Consulta AFIP y persistencia de datos fiscales
"""

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, joinedload

from app.core.logging import get_logger
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.proveedor_datos_fiscales import ProveedorDatosFiscales
from app.models.rma_proveedor import RmaProveedor
from app.models.tb_supplier import TBSupplier
from app.services.afip_service import AfipService, AfipServiceError

logger = get_logger(__name__)


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
        """Obtiene un proveedor por ID con datos fiscales incluidos."""
        return (
            self.db.query(Proveedor)
            .options(joinedload(Proveedor.datos_fiscales))
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

    def sync_desde_erp(self) -> dict[str, int]:
        """
        Sincroniza proveedores desde tb_supplier a la tabla central.

        - Inserta proveedores nuevos (que no existan por supp_id+comp_id)
        - Actualiza nombre y CUIT de existentes si cambiaron en ERP
        - Vincula rma_proveedores existentes al proveedor central

        Retorna contadores: {insertados, actualizados, vinculados_rma, total_erp}
        """
        erp_suppliers = self.db.query(TBSupplier).all()

        # Index proveedores existentes por (comp_id, supp_id)
        existing: dict[tuple[int, int], Proveedor] = {
            (p.comp_id, p.supp_id): p for p in self.db.query(Proveedor).filter(Proveedor.supp_id.isnot(None)).all()
        }

        # Index rma_proveedores sin vincular
        rma_sin_vincular: dict[tuple[int, int], RmaProveedor] = {
            (r.comp_id, r.supp_id): r
            for r in self.db.query(RmaProveedor)
            .filter(RmaProveedor.supp_id.isnot(None), RmaProveedor.proveedor_id.is_(None))
            .all()
        }

        insertados = 0
        actualizados = 0
        vinculados_rma = 0

        for supp in erp_suppliers:
            key = (supp.comp_id, supp.supp_id)

            if key in existing:
                prov = existing[key]
                # Solo actualizar nombre y CUIT (no pisar datos extendidos)
                changed = False
                if prov.nombre != supp.supp_name:
                    prov.nombre = supp.supp_name
                    changed = True
                if prov.cuit != supp.supp_tax_number:
                    prov.cuit = supp.supp_tax_number
                    changed = True
                if changed:
                    actualizados += 1
            else:
                prov = Proveedor(
                    supp_id=supp.supp_id,
                    comp_id=supp.comp_id,
                    nombre=supp.supp_name,
                    cuit=supp.supp_tax_number,
                    origen=OrigenProveedor.ERP,
                )
                self.db.add(prov)
                self.db.flush()  # para obtener prov.id
                existing[key] = prov
                insertados += 1

            # Vincular rma_proveedor si existe y no está vinculado
            if key in rma_sin_vincular:
                rma = rma_sin_vincular[key]
                rma.proveedor_id = prov.id
                vinculados_rma += 1

        self.db.commit()

        logger.info(
            "Sync proveedores ERP: insertados=%d, actualizados=%d, vinculados_rma=%d, total_erp=%d",
            insertados,
            actualizados,
            vinculados_rma,
            len(erp_suppliers),
        )

        return {
            "insertados": insertados,
            "actualizados": actualizados,
            "vinculados_rma": vinculados_rma,
            "total_erp": len(erp_suppliers),
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
