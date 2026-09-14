"""
RED/GREEN — `sync_item_taxes_full` debe reemplazar el tax_id local cuando el
ERP lo cambia (el bug real: el ERP corrige tb_item_taxes sin tocar tb_item,
así que el sync incremental nunca ve el cambio y el espejo local queda con
el IVA viejo para siempre).

Cubre también los dos safeguards contra fallos transitorios del ERP: una
respuesta vacía y la respuesta centinela `[{"Column1": ...}]` no deben
borrar nada.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.tb_item_taxes import TBItemTaxes
from app.services.erp_item_taxes_sync import sync_item_taxes_full


def _mock_response(payload):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=payload)
    return response


class TestSyncItemTaxesFull:
    def test_replaces_old_tax_id_with_new_one_from_erp(self, db) -> None:
        # Estado local viejo: item 42 con tax_id 5 (el que el ERP ya corrigió).
        # tax_class se guarda como "1" (string) porque el modelo declara
        # String(50), pero producción persiste vía `to_int(...)`, así que
        # el valor efectivamente guardado ya es un int (ver test abajo).
        db.add(TBItemTaxes(comp_id=1, item_id=42, tax_id=5, tax_class="1"))
        db.commit()

        erp_payload = [
            {"comp_id": 1, "item_id": 42, "tax_id": 8, "tax_class": "2"},
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(erp_payload))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.erp_item_taxes_sync.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(sync_item_taxes_full(db))

        rows = db.query(TBItemTaxes).filter(TBItemTaxes.item_id == 42).all()
        assert len(rows) == 1
        assert rows[0].tax_id == 8
        # El código llama `to_int("2")` -> 2 (int) antes de asignarlo a
        # tax_class, pero el modelo declara tax_class como String(50): la
        # columna tiene afinidad TEXT y SQLite lo devuelve como "2" (str) al
        # releer tras el commit. Esto refleja el comportamiento real
        # persistido, no lo que el código "intenta" escribir.
        assert rows[0].tax_class == "2"
        assert result == {"insertados": 1, "items_reemplazados": 1}

    def test_delete_scoped_to_comp_id_item_id_pair_not_item_id_alone(self, db) -> None:
        # Dos comp_id distintas con el MISMO item_id (la PK real es compuesta).
        # El ERP solo devuelve la fila de comp_id=1; la de comp_id=2 no debe
        # borrarse (bug viejo: el delete filtraba solo por item_id y se
        # llevaba puesta la fila de la otra comp_id sin volver a insertarla).
        db.add(TBItemTaxes(comp_id=1, item_id=42, tax_id=5, tax_class="1"))
        db.add(TBItemTaxes(comp_id=2, item_id=42, tax_id=9, tax_class="3"))
        db.commit()

        erp_payload = [
            {"comp_id": 1, "item_id": 42, "tax_id": 8, "tax_class": "2"},
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(erp_payload))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.erp_item_taxes_sync.httpx.AsyncClient", return_value=mock_client):
            asyncio.run(sync_item_taxes_full(db))

        rows = db.query(TBItemTaxes).filter(TBItemTaxes.item_id == 42).order_by(TBItemTaxes.comp_id).all()
        assert len(rows) == 2
        assert rows[0].comp_id == 1
        assert rows[0].tax_id == 8
        assert rows[1].comp_id == 2
        assert rows[1].tax_id == 9

    def test_empty_response_does_not_delete_existing_rows(self, db) -> None:
        db.add(TBItemTaxes(comp_id=1, item_id=42, tax_id=5, tax_class="A"))
        db.commit()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response([]))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.erp_item_taxes_sync.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(sync_item_taxes_full(db))

        rows = db.query(TBItemTaxes).filter(TBItemTaxes.item_id == 42).all()
        assert len(rows) == 1
        assert rows[0].tax_id == 5
        assert result == {"insertados": 0, "items_reemplazados": 0}

    def test_sentinel_response_does_not_delete_existing_rows(self, db) -> None:
        db.add(TBItemTaxes(comp_id=1, item_id=42, tax_id=5, tax_class="A"))
        db.commit()

        sentinel_payload = [{"Column1": None}]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(sentinel_payload))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.erp_item_taxes_sync.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(sync_item_taxes_full(db))

        rows = db.query(TBItemTaxes).filter(TBItemTaxes.item_id == 42).all()
        assert len(rows) == 1
        assert rows[0].tax_id == 5
        assert result == {"insertados": 0, "items_reemplazados": 0}
