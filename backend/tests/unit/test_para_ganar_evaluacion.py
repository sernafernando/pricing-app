"""P5 Slice A: first-run / R1–R3 evaluation + Periodicidad MLA scope."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models.para_ganar_revision_mla import ParaGanarRevisionMla
from app.services.para_ganar_evaluacion import (
    baseline_from_sugerencia,
    evaluar_mla,
    evaluar_periodicidad,
    list_mlas_periodicidad_enabled,
    pendiente_reasons,
)
from app.services.para_ganar_sugerencia import SugerenciaMla
from tests.conftest import make_access_token


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def _sug(**overrides: object) -> SugerenciaMla:
    payload = dict(
        mla="MLA100",
        catalog_product_id="CAT-1",
        snapshot_at=datetime(2026, 10, 1, tzinfo=UTC),
        our_price=100.0,
        our_rank=1,
        top_sellers=5,
        in_top=True,
        suggestion_status="winning",
        delta_ars=0.0,
        needs_competition_refresh=False,
    )
    payload.update(overrides)
    return SugerenciaMla(**payload)  # type: ignore[arg-type]


def test_first_eval_is_pendiente_and_second_same_state_is_sin_novedades(db, monkeypatch) -> None:
    current = _sug()
    monkeypatch.setattr(
        "app.services.para_ganar_evaluacion.compute_sugerencia_mla",
        lambda _db, _mla: current,
    )

    first = evaluar_mla(db, "MLA100", updated_by_id=None)
    assert first == "pendiente"
    row = db.get(ParaGanarRevisionMla, "MLA100")
    assert row is not None
    assert row.estado == "pendiente"
    assert row.competition_baseline["our_rank"] == 1
    assert row.competition_baseline["suggestion_status"] == "winning"
    assert row.competition_baseline["in_top"] is True

    second = evaluar_mla(db, "MLA100", updated_by_id=None)
    assert second == "sin_novedades"
    row = db.get(ParaGanarRevisionMla, "MLA100")
    assert row.estado == "sin_novedades"
    assert row.competition_baseline["our_rank"] == 1


def test_rank_worsen_or_lost_top_is_pendiente() -> None:
    baseline = baseline_from_sugerencia(_sug(our_rank=1, in_top=True, suggestion_status="winning"))
    worse_rank = _sug(our_rank=3, in_top=True, suggestion_status="winning", delta_ars=0.0)
    assert "r1" in pendiente_reasons(baseline, worse_rank)

    lost_top = _sug(our_rank=6, in_top=False, suggestion_status="winning", delta_ars=0.0)
    assert "r1" in pendiente_reasons(baseline, lost_top)


def test_losing_after_not_losing_is_pendiente() -> None:
    baseline = baseline_from_sugerencia(_sug(suggestion_status="winning", our_rank=1))
    losing = _sug(suggestion_status="losing", our_rank=1, in_top=True, delta_ars=-5.0)
    assert pendiente_reasons(baseline, losing) == ["r2"]

    alone_base = baseline_from_sugerencia(_sug(suggestion_status="alone", our_rank=1))
    assert "r2" in pendiente_reasons(alone_base, losing)


def test_winning_with_delta_room_is_pendiente() -> None:
    baseline = baseline_from_sugerencia(_sug(our_rank=2, suggestion_status="winning", delta_ars=0.0))
    room = _sug(our_rank=2, suggestion_status="winning", delta_ars=10.0, in_top=True)
    assert pendiente_reasons(baseline, room) == ["r3"]

    worse_rank = _sug(our_rank=3, suggestion_status="winning", delta_ars=10.0, in_top=True)
    reasons = pendiente_reasons(baseline, worse_rank)
    assert "r1" in reasons
    assert "r3" not in reasons


def test_skip_when_needs_refresh_or_no_catalog(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.para_ganar_evaluacion.compute_sugerencia_mla",
        lambda _db, _mla: _sug(needs_competition_refresh=True, catalog_product_id="CAT-1"),
    )
    assert evaluar_mla(db, "MLA100", updated_by_id=None) is None
    assert db.get(ParaGanarRevisionMla, "MLA100") is None

    monkeypatch.setattr(
        "app.services.para_ganar_evaluacion.compute_sugerencia_mla",
        lambda _db, _mla: _sug(catalog_product_id=None, needs_competition_refresh=False),
    )
    assert evaluar_mla(db, "MLA100", updated_by_id=None) is None
    assert db.get(ParaGanarRevisionMla, "MLA100") is None


def test_rerun_overwrites_estado(db, monkeypatch) -> None:
    states = iter(
        [
            _sug(our_rank=1, suggestion_status="winning", delta_ars=0.0),
            _sug(our_rank=1, suggestion_status="winning", delta_ars=0.0),
            _sug(our_rank=4, suggestion_status="winning", delta_ars=0.0, in_top=True),
        ]
    )
    monkeypatch.setattr(
        "app.services.para_ganar_evaluacion.compute_sugerencia_mla",
        lambda _db, _mla: next(states),
    )
    assert evaluar_mla(db, "MLA100", updated_by_id=None) == "pendiente"
    assert evaluar_mla(db, "MLA100", updated_by_id=None) == "sin_novedades"
    assert evaluar_mla(db, "MLA100", updated_by_id=None) == "pendiente"
    assert db.get(ParaGanarRevisionMla, "MLA100").estado == "pendiente"


def test_list_mlas_periodicidad_enabled_respects_scope_and_catalog(db) -> None:
    from app.models.ml_publication_link import MlPublicationLink
    from app.models.para_ganar_periodicidad import (
        ParaGanarPeriodicidadEan,
        ParaGanarPeriodicidadEanMla,
    )
    from app.models.producto import ProductoERP
    from app.models.publicacion_ml import PublicacionML

    producto = ProductoERP(item_id=88101, codigo="779888100", descripcion="eval scope", costo=10)
    db.add(producto)
    db.flush()
    for mla, pricelist, catalog in (
        ("MLA88101", 4, True),
        ("MLA88102", 14, True),
        ("MLA88103", 4, False),
    ):
        db.add(
            PublicacionML(
                mla=mla,
                item_id=producto.item_id,
                codigo="779888100",
                activo=True,
                pricelist_id=pricelist,
            )
        )
        db.add(MlPublicationLink(mla=mla, catalog_product_id="CAT-EVAL", catalog_listing=catalog))

    disabled = ParaGanarPeriodicidadEan(ean="779888199", enabled=False, scope_mode="all")
    db.add(disabled)
    other = ProductoERP(item_id=88102, codigo="779888199", descripcion="disabled ean", costo=10)
    db.add(other)
    db.flush()
    db.add(PublicacionML(mla="MLA88199", item_id=other.item_id, codigo="779888199", activo=True, pricelist_id=4))
    db.add(MlPublicationLink(mla="MLA88199", catalog_product_id="CAT-OFF", catalog_listing=True))

    sub_all = ParaGanarPeriodicidadEan(ean="779888100", enabled=True, scope_mode="all")
    db.add(sub_all)
    db.flush()
    assert set(list_mlas_periodicidad_enabled(db)) == {"MLA88101", "MLA88102"}

    sub_all.scope_mode = "mlas"
    db.add(ParaGanarPeriodicidadEanMla(ean="779888100", mla="MLA88102"))
    db.flush()
    assert list_mlas_periodicidad_enabled(db) == ["MLA88102"]

    sub_all.scope_mode = "rules"
    sub_all.tipos_publicacion = ["6"]
    sub_all.pricelist_ids = []
    sub_all.tienda_oficial_ids = []
    db.flush()
    assert list_mlas_periodicidad_enabled(db) == ["MLA88102"]


def test_evaluar_periodicidad_counts_skip_and_eval(db, monkeypatch) -> None:
    from app.models.ml_publication_link import MlPublicationLink
    from app.models.para_ganar_periodicidad import ParaGanarPeriodicidadEan
    from app.models.producto import ProductoERP
    from app.models.publicacion_ml import PublicacionML

    producto = ProductoERP(item_id=88111, codigo="779888200", descripcion="eval batch", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88211", item_id=producto.item_id, codigo="779888200", activo=True, pricelist_id=4))
    db.add(PublicacionML(mla="MLA88212", item_id=producto.item_id, codigo="779888200", activo=True, pricelist_id=4))
    db.add(MlPublicationLink(mla="MLA88211", catalog_product_id="CAT-B", catalog_listing=True))
    db.add(MlPublicationLink(mla="MLA88212", catalog_product_id="CAT-B", catalog_listing=True))
    db.add(ParaGanarPeriodicidadEan(ean="779888200", enabled=True, scope_mode="all"))
    db.commit()

    def _fake_bulk(_db, mlas: list[str]) -> dict[str, SugerenciaMla]:
        out: dict[str, SugerenciaMla] = {}
        for mla in mlas:
            if mla == "MLA88212":
                out[mla] = _sug(mla=mla, needs_competition_refresh=True)
            else:
                out[mla] = _sug(mla=mla)
        return out

    monkeypatch.setattr("app.services.para_ganar_evaluacion.compute_sugerencia_mlas_bulk", _fake_bulk)
    counts = evaluar_periodicidad(db, updated_by_id=None)
    assert counts["evaluated"] == 1
    assert counts["pendiente"] == 1
    assert counts["sin_novedades"] == 0
    assert counts["skipped"] == 1


def test_evaluar_endpoint_requires_auth_and_writes(client: TestClient, rma_superadmin_user, db, monkeypatch) -> None:
    from app.models.ml_publication_link import MlPublicationLink
    from app.models.para_ganar_periodicidad import ParaGanarPeriodicidadEan
    from app.models.producto import ProductoERP
    from app.models.publicacion_ml import PublicacionML

    assert client.post("/api/para-ganar/periodicidad/evaluar").status_code in (401, 403)

    producto = ProductoERP(item_id=88121, codigo="779888300", descripcion="eval http", costo=10)
    db.add(producto)
    db.flush()
    db.add(PublicacionML(mla="MLA88301", item_id=producto.item_id, codigo="779888300", activo=True, pricelist_id=4))
    db.add(MlPublicationLink(mla="MLA88301", catalog_product_id="CAT-H", catalog_listing=True))
    db.add(ParaGanarPeriodicidadEan(ean="779888300", enabled=True, scope_mode="all"))
    db.commit()

    monkeypatch.setattr(
        "app.services.para_ganar_evaluacion.compute_sugerencia_mlas_bulk",
        lambda _db, mlas: {mla: _sug(mla=mla) for mla in mlas},
    )
    response = client.post(
        "/api/para-ganar/periodicidad/evaluar",
        headers=_auth(rma_superadmin_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evaluated"] == 1
    assert body["pendiente"] == 1
    assert body["skipped"] == 0
    row = db.get(ParaGanarRevisionMla, "MLA88301")
    assert row is not None
    assert row.estado == "pendiente"
    assert row.competition_baseline is not None
