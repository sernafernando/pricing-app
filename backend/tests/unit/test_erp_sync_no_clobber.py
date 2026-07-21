"""
RED/GREEN — ERP incremental sync must never clobber `ml_publication_links`
(productos-catalog-family-tree PR1b, task 4).

Spec req: "Link fields MUST persist outside the ERP-synced table" /
"ERP sync runs after link fields are stored" scenario. The ERP sync's
`setattr` loop (`sync_ml_items_publicados_incremental.procesar_items`)
only ever `setattr`s onto `MercadoLibreItemPublicado` instances — an
entirely separate table/model from `MlPublicationLink`. This test proves
that structurally: running the ERP sync's item-processing loop over a
publication row leaves an existing `ml_publication_links` row for the
same mla completely untouched.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.models.ml_publication_link import MlPublicationLink
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.scripts.sync_ml_items_publicados_incremental import procesar_items


class TestErpSyncNoClobber:
    def test_erp_incremental_sync_does_not_touch_publication_links(self, db) -> None:
        fetched_at = datetime.now(timezone.utc)
        db.add(
            MlPublicationLink(
                mla="MLA2361127120",
                family_id="FAM_ORIGINAL",
                user_product_id="UP_ORIGINAL",
                item_id=42,
                fetched_at=fetched_at,
            )
        )
        db.commit()

        erp_item_payload = {
            "mlp_id": 999,
            "item_id": 42,
            "mlp_publicationID": "MLA2361127120",
            "mlp_itemTitle": "Updated title from ERP",
            "mlp_price": 1234.56,
            "curr_id": 1,
        }

        asyncio.run(procesar_items(db, [erp_item_payload], tipo="test"))
        db.commit()

        link_row = db.query(MlPublicationLink).filter(MlPublicationLink.mla == "MLA2361127120").first()
        assert link_row is not None
        assert link_row.family_id == "FAM_ORIGINAL"
        assert link_row.user_product_id == "UP_ORIGINAL"
        # sqlite strips tzinfo on round-trip; compare naive wall-clock value.
        assert link_row.fetched_at.replace(tzinfo=None) == fetched_at.replace(tzinfo=None)

        erp_row = db.query(MercadoLibreItemPublicado).filter(MercadoLibreItemPublicado.mlp_id == 999).first()
        assert erp_row is not None
        assert erp_row.mlp_itemTitle == "Updated title from ERP"
