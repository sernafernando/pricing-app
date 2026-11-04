"""ml-ads-aportes "Por aporte" view on real Postgres: "Cargado" reads the aporte's id out of `auditoria`'s JSON.

`auditoria` holds every module's rows; another type may carry a non-numeric "id". The lookup compares as text, so no
row of another type can break it, whatever order Postgres applies the filters in. DERIVED rows.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import insert

from app.models.auditoria import TipoAccion
from app.services.ml_ads import contributions
from tests.services.ml_ads.conftest import AUDIT_STANDIN

pytestmark = pytest.mark.postgres


def _audit(db, tipo: TipoAccion, nuevos, when: datetime, user_id: int = 1) -> None:
    db.execute(
        insert(AUDIT_STANDIN).values(
            usuario_id=user_id, tipo_accion=tipo, valores_nuevos=nuevos, valores_anteriores=None, fecha=when
        )
    )


def test_the_trail_finds_the_aporte_rows_among_other_types_with_non_numeric_ids(pg_ads_write_db) -> None:
    db = pg_ads_write_db
    _audit(db, TipoAccion.ML_ADS_APORTE_CREADO, {"id": 41}, datetime(2026, 10, 2, 10, 0), user_id=7)
    _audit(db, TipoAccion.ML_ADS_APORTE_EDITADO, {"id": 41}, datetime(2026, 10, 18, 16, 0), user_id=8)
    _audit(db, TipoAccion.ML_ADS_APORTE_CREADO, {"id": 42}, datetime(2026, 10, 3, 9, 0))
    _audit(db, TipoAccion.MODIFICAR_PRECIO_CLASICA, {"id": "MLA123", "precio": 10}, datetime(2026, 10, 4))
    _audit(db, TipoAccion.MODIFICAR_PRECIO_CLASICA, {"precio": 10}, datetime(2026, 10, 5))
    db.flush()
    trail = contributions._audit_trail(db, [41, 99])
    assert trail == {
        41: [
            (TipoAccion.ML_ADS_APORTE_CREADO, 7, datetime(2026, 10, 2, 10, 0)),
            (TipoAccion.ML_ADS_APORTE_EDITADO, 8, datetime(2026, 10, 18, 16, 0)),
        ]
    }


def test_the_history_reads_the_id_from_before_on_a_delete(pg_ads_write_db, monkeypatch) -> None:
    db = pg_ads_write_db
    # This schema has no `usuarios`; the names are the router tests' job.
    monkeypatch.setattr(contributions, "_user_names", lambda _db, _ids: {})
    db.execute(
        insert(contributions.MlAdsCampaignContribution.__table__).values(
            id=55,
            advertiser_id=714700,
            campaign_id=1,
            channel="product_ads",
            kind="percentage",
            value=10,
            date_from=datetime(2026, 10, 1).date(),
            date_to=datetime(2026, 10, 31).date(),
            created_by_id=7,
            updated_by_id=7,
        )
    )
    _audit(db, TipoAccion.ML_ADS_APORTE_CREADO, {"id": 55}, datetime(2026, 10, 2))
    db.execute(
        insert(AUDIT_STANDIN).values(
            usuario_id=8,
            tipo_accion=TipoAccion.ML_ADS_APORTE_BORRADO,
            valores_anteriores={"id": 55},
            valores_nuevos=None,
            fecha=datetime(2026, 10, 9),
        )
    )
    _audit(db, TipoAccion.MODIFICAR_PRECIO_CLASICA, {"id": "MLA55"}, datetime(2026, 10, 4))
    db.flush()
    assert [(e.action, e.at) for e in contributions.history(db, 55)] == [
        ("created", datetime(2026, 10, 2)),
        ("deleted", datetime(2026, 10, 9)),
    ]
