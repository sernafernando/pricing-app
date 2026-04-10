from sqlalchemy.orm import Session
from sqlalchemy import func, tuple_
from typing import Optional

from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.marca_pm import MarcaPM
from app.models.usuario import Usuario, RolUsuario


def aplicar_filtro_marcas_pm(query, usuario: Usuario, db: Session, pm_ids: Optional[str] = None):
    """
    Aplica filtro de pares marca+categoría del PM a una query de MLVentaMetrica.

    Si pm_ids está presente (usuario admin seleccionó PMs específicos), filtra por esos PMs.
    Si pm_ids NO está presente, aplica el filtro del usuario actual (comportamiento original).
    """
    # Si el usuario admin pasó pm_ids, usar esos en lugar del usuario actual
    # SEGURIDAD: solo roles admin/gerente pueden usar pm_ids para ver datos de otros PMs
    if pm_ids:
        roles_admin = [RolUsuario.SUPERADMIN, RolUsuario.ADMIN, RolUsuario.GERENTE]
        if usuario.rol not in roles_admin:
            pm_ids = None  # Ignorar pm_ids para usuarios no admin

    if pm_ids:
        pm_ids_list = [int(id.strip()) for id in pm_ids.split(",") if id.strip().isdigit()]
        if pm_ids_list:
            pares_pm = (
                db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids_list)).distinct().all()
            )

            if not pares_pm:
                query = query.filter(MLVentaMetrica.marca == "__NINGUNA__")
            else:
                pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
                query = query.filter(
                    tuple_(func.upper(MLVentaMetrica.marca), func.upper(MLVentaMetrica.categoria)).in_(pares_upper)
                )
            return query

    # Comportamiento original: filtrar por marcas+categorías del usuario actual
    roles_completos = [RolUsuario.SUPERADMIN, RolUsuario.ADMIN, RolUsuario.GERENTE]

    if usuario.rol in roles_completos:
        return query  # No filtrar

    pares = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id == usuario.id).all()

    if not pares:
        query = query.filter(MLVentaMetrica.marca == "__NINGUNA__")
    else:
        pares_upper = [(m.upper(), c.upper()) for m, c in pares]
        query = query.filter(
            tuple_(func.upper(MLVentaMetrica.marca), func.upper(MLVentaMetrica.categoria)).in_(pares_upper)
        )

    return query


def aplicar_filtro_tienda_oficial(query, tiendas_oficiales: Optional[str], db: Session):
    """
    Aplica filtro de tiendas oficiales por mlp_official_store_id.
    Soporta múltiples tiendas separadas por coma.

    Tiendas disponibles:
    - 57997: Gauss
    - 2645: TP-Link
    - 144: Forza/Verbatim
    - 191942: Multi-marca (Epson, Logitech, MGN, Razer)
    """
    if tiendas_oficiales:
        from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
        from sqlalchemy import cast, String

        # Parsear múltiples tiendas
        store_ids = [int(id.strip()) for id in tiendas_oficiales.split(",") if id.strip().isdigit()]

        if store_ids:
            # Subquery para obtener mlp_ids de tiendas oficiales
            mlas_tienda_oficial = (
                db.query(cast(MercadoLibreItemPublicado.mlp_id, String))
                .filter(MercadoLibreItemPublicado.mlp_official_store_id.in_(store_ids))
                .distinct()
            )

            query = query.filter(MLVentaMetrica.mla_id.in_(mlas_tienda_oficial))
    return query
