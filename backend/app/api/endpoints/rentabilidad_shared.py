from sqlalchemy.orm import Session
from typing import Optional

from app.models.ml_venta_metrica import MLVentaMetrica
from app.services.pm_scope import aplicar_filtro_marcas_pm as _aplicar_filtro_marcas_pm

# Re-exported: reference gate implementation (D2), now shared via pm_scope.py.
aplicar_filtro_marcas_pm = _aplicar_filtro_marcas_pm


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
