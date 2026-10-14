"""
REGRESSION (prod, MLA1391137819): the promotions tree showed the "Activa"
status chip AND the "Publicación pausada" banner for the same MLA.

The chip read the ERP mirror (`tb_mercadolibre_items_publicados`, synced
months ago) while the banner read the ML publications store (`ml_items`).
Owner decision: `ml_items` is the source of truth for a publication's
status everywhere. These tests seed the two stores DISAGREEING (exactly the
prod shape) and pin that the chip (`publication_status` on the tree node)
and the banner (`motivo_sin_consulta_ml`, served as
`motivo_sin_actualizacion`) both follow `ml_items`, so they can never
disagree again.
"""

from __future__ import annotations

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_publication_link import MlPublicationLink
from app.models.ml_publications import MlItem
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.routers.ml_promotions import motivo_sin_consulta_ml
from app.services.ml_publication_tree_service import assemble_publication_tree

MOTIVO_PAUSADA = "Publicación pausada: las promos se actualizan cuando se reactive"

# ERP `mlp_lastStatusID` ids: 153 = active, 154 = paused.
ERP_ACTIVE = 153
ERP_PAUSED = 154


def _seed(db, item_id: int, mla: str, ml_status: str, erp_status_id: int) -> None:
    db.add(ProductoERP(item_id=item_id, codigo=f"COD{item_id}", descripcion=f"Producto {item_id}"))
    db.add(PublicacionML(mla=mla, item_id=item_id, pricelist_id=4, activo=True))
    db.add(MlPublicationLink(mla=mla, item_id=item_id))
    db.add(MlItem(item_id=mla, status=ml_status, sub_status=["paused_by_seller"] if ml_status == "paused" else []))
    db.add(MercadoLibreItemPublicado(mlp_publicationID=mla, mlp_lastStatusID=erp_status_id, mlp_Active=True))
    db.commit()


def _chip(db, item_id: int) -> str | None:
    return assemble_publication_tree(db, item_id=item_id).tree.children[0].publication_status


def test_paused_in_ml_items_shows_paused_chip_and_banner_even_if_erp_says_active(db) -> None:
    _seed(db, 901, "MLA_PARITY_PAUSED", ml_status="paused", erp_status_id=ERP_ACTIVE)

    assert _chip(db, 901) == "paused"
    assert motivo_sin_consulta_ml(db, "MLA_PARITY_PAUSED") == MOTIVO_PAUSADA


def test_active_in_ml_items_shows_active_chip_and_no_banner_even_if_erp_says_paused(db) -> None:
    _seed(db, 902, "MLA_PARITY_ACTIVE", ml_status="active", erp_status_id=ERP_PAUSED)

    assert _chip(db, 902) == "active"
    assert motivo_sin_consulta_ml(db, "MLA_PARITY_ACTIVE") is None
