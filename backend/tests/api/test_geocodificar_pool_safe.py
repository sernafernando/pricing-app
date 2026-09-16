"""Regression tests for pool-safe geocodificación masiva (2026-09-16 incident follow-up).

`POST /etiquetas-envio/geocodificar` used to hold the request-scoped DB session
open across up to 200 sequential Mapbox/Nominatim HTTP calls (each with a rate
limit `asyncio.sleep(1.1)` on fallback). 200 × ~1.1s ≈ 220s > the 120s
`idle_in_transaction_session_timeout`, so Postgres killed the session mid-batch.

The contract pinned down here: while `geocode_address` is being awaited, no
`get_background_db()` context is open. Business-logic tests pin the exact
counters (`geocodificados` / `ya_tenian` / `sin_resultado` / `errores`) for
every branch of the transporte→cliente fallback chain, using the SAME
`get_background_db` patch pattern as `tests/unit/test_prearmado_validar_serial.py`
(the test's own `db` fixture stands in for every short-lived session).
"""

import asyncio
from contextlib import contextmanager
from datetime import date
from typing import Generator, List, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.api.endpoints import etiquetas_enrichment as mod
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.transporte import Transporte


@pytest.fixture(autouse=True)
def _patch_bg_db(db: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Patches `etiquetas_enrichment.get_background_db` with a CM that yields
    the test `db` fixture. The fake CM does NOT commit/close — the `db`
    fixture owns the session lifecycle and rolls back after each test
    (see `tests/unit/test_prearmado_validar_serial.py` for the same pattern).
    """

    @contextmanager
    def _fake_bg_db() -> Generator[Session, None, None]:
        yield db

    monkeypatch.setattr(mod, "get_background_db", _fake_bg_db)


@pytest.fixture(autouse=True)
def _patch_permiso_and_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_check_permiso", lambda *a, **kw: None)
    monkeypatch.setattr(mod, "sse_publish_bg", lambda *a, **kw: None)


def _crear_etiqueta(db: Session, shipping_id: str, **kwargs) -> EtiquetaEnvio:
    defaults = dict(
        shipping_id=shipping_id,
        fecha_envio=date(2026, 9, 16),
        latitud=None,
        longitud=None,
    )
    defaults.update(kwargs)
    e = EtiquetaEnvio(**defaults)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _crear_transporte(db: Session, nombre: str, **kwargs) -> Transporte:
    defaults = dict(nombre=nombre)
    defaults.update(kwargs)
    t = Transporte(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _crear_ml_shipping(db: Session, shipping_id: str, **kwargs) -> MercadoLibreOrderShipping:
    defaults = dict(
        mlm_id=int(shipping_id) if shipping_id.isdigit() else abs(hash(shipping_id)) % (10**9),
        mlshippingid=shipping_id,
    )
    defaults.update(kwargs)
    ml = MercadoLibreOrderShipping(**defaults)
    db.add(ml)
    db.commit()
    return ml


def _body(shipping_ids: List[str]) -> mod.GeocodificarRequest:
    return mod.GeocodificarRequest(shipping_ids=shipping_ids)


def _run(body, db) -> mod.GeocodificarResponse:
    result = asyncio.run(mod.geocodificar_etiquetas(body, db=db, current_user=MagicMock()))
    # PHASE 3 writes via bulk UPDATE (synchronize_session=False), which never
    # touches objects already cached in this shared test session's identity
    # map. In production PHASE 1/PHASE 3 use genuinely separate sessions, so
    # this staleness never happens there — it's purely an artifact of reusing
    # one `db` session as the stand-in for every short-lived session here.
    db.expire_all()
    return result


# ── Pool-safety contract ──────────────────────────────────────────────


def test_no_bg_session_open_during_http_call(db: Session, monkeypatch: pytest.MonkeyPatch):
    """The key contract: while geocode_address (HTTP) runs, no get_background_db
    context is currently open — i.e. PHASE 1's read session was already closed."""
    _crear_etiqueta(db, "S1", direccion_completa="Calle Falsa 123")

    events: List[str] = []

    @contextmanager
    def _tracking_bg_db() -> Generator[Session, None, None]:
        events.append("open")
        try:
            yield db
        finally:
            events.append("close")

    monkeypatch.setattr(mod, "get_background_db", _tracking_bg_db)

    async def fake_geocode(*args, **kwargs) -> Optional[tuple]:
        events.append("http")
        assert events.count("open") == events.count("close"), (
            f"a get_background_db() session was still open during the HTTP call: {events}"
        )
        return (1.0, 2.0)

    monkeypatch.setattr(mod, "geocode_address", fake_geocode)

    result = _run(_body(["S1"]), db)

    assert "http" in events
    assert result.geocodificados == 1


def test_no_bg_session_open_during_transporte_and_cliente_http_calls(db: Session, monkeypatch: pytest.MonkeyPatch):
    """Same contract, but for the two-HTTP-call chain (transporte fails → cliente fallback)."""
    transporte = _crear_transporte(db, "Transporte Fail", direccion="Ruta 1 km 5", localidad="Rosario")
    _crear_etiqueta(
        db,
        "S2",
        transporte_id=transporte.id,
        direccion_completa="Calle Real 456",
    )

    events: List[str] = []

    @contextmanager
    def _tracking_bg_db() -> Generator[Session, None, None]:
        events.append("open")
        try:
            yield db
        finally:
            events.append("close")

    monkeypatch.setattr(mod, "get_background_db", _tracking_bg_db)

    async def fake_geocode(direccion, *args, **kwargs) -> Optional[tuple]:
        events.append(f"http:{direccion}")
        assert events.count("open") == events.count("close"), (
            f"a get_background_db() session was still open during the HTTP call: {events}"
        )
        if direccion == "Ruta 1 km 5":
            return None  # transporte geocode fails
        return (10.0, 20.0)

    monkeypatch.setattr(mod, "geocode_address", fake_geocode)

    result = _run(_body(["S2"]), db)

    assert any(e.startswith("http:Ruta 1 km 5") for e in events)
    assert any(e.startswith("http:Calle Real 456") for e in events)
    assert result.geocodificados == 1


# ── Business-logic: counters per branch ────────────────────────────────


def test_transporte_con_coords_actualiza_etiqueta(db: Session, monkeypatch: pytest.MonkeyPatch):
    transporte = _crear_transporte(db, "T Coords", latitud=-34.6, longitud=-58.4)
    _crear_etiqueta(db, "S3", transporte_id=transporte.id, latitud=-1.0, longitud=-1.0)

    async def fail_if_called(*a, **kw):
        raise AssertionError("no debería llamar a geocode_address: el transporte ya tenía coords")

    monkeypatch.setattr(mod, "geocode_address", fail_if_called)

    result = _run(_body(["S3"]), db)

    assert result.geocodificados == 1
    assert result.ya_tenian == 0
    updated = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == "S3").first()
    assert updated.latitud == -34.6
    assert updated.longitud == -58.4


def test_transporte_con_coords_iguales_a_las_ya_guardadas_cuenta_ya_tenian(
    db: Session, monkeypatch: pytest.MonkeyPatch
):
    transporte = _crear_transporte(db, "T Coords Same", latitud=-34.6, longitud=-58.4)
    _crear_etiqueta(db, "S4", transporte_id=transporte.id, latitud=-34.6, longitud=-58.4)

    async def fail_if_called(*a, **kw):
        raise AssertionError("no debería llamar a geocode_address")

    monkeypatch.setattr(mod, "geocode_address", fail_if_called)

    result = _run(_body(["S4"]), db)

    assert result.geocodificados == 0
    assert result.ya_tenian == 1


def test_transporte_sin_coords_con_direccion_geocodifica_y_persiste_en_transporte(
    db: Session, monkeypatch: pytest.MonkeyPatch
):
    transporte = _crear_transporte(db, "T SinCoords", direccion="Av. Siempreviva 742", localidad="Springfield")
    _crear_etiqueta(db, "S5", transporte_id=transporte.id)

    async def fake_geocode(direccion, ciudad="Buenos Aires", **kw):
        assert direccion == "Av. Siempreviva 742"
        assert ciudad == "Springfield"
        return (5.0, 6.0)

    monkeypatch.setattr(mod, "geocode_address", fake_geocode)

    result = _run(_body(["S5"]), db)

    assert result.geocodificados == 1
    updated_transporte = db.query(Transporte).filter(Transporte.id == transporte.id).first()
    assert updated_transporte.latitud == 5.0
    assert updated_transporte.longitud == 6.0
    updated_etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == "S5").first()
    assert updated_etiqueta.latitud == 5.0
    assert updated_etiqueta.longitud == 6.0


def test_transporte_sin_coords_ni_direccion_cae_al_fallback_cliente(db: Session, monkeypatch: pytest.MonkeyPatch):
    transporte = _crear_transporte(db, "T Vacio")
    _crear_etiqueta(db, "S6", transporte_id=transporte.id, direccion_completa="Calle Cliente 999")

    async def fake_geocode(direccion, **kw):
        assert direccion == "Calle Cliente 999"
        return (7.0, 8.0)

    monkeypatch.setattr(mod, "geocode_address", fake_geocode)

    result = _run(_body(["S6"]), db)

    assert result.geocodificados == 1
    updated = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == "S6").first()
    assert updated.latitud == 7.0
    assert updated.longitud == 8.0


def test_etiqueta_sin_transporte_que_ya_tiene_coords_cuenta_ya_tenian(db: Session, monkeypatch: pytest.MonkeyPatch):
    _crear_etiqueta(db, "S7", latitud=1.0, longitud=2.0)

    async def fail_if_called(*a, **kw):
        raise AssertionError("no debería llamar a geocode_address")

    monkeypatch.setattr(mod, "geocode_address", fail_if_called)

    result = _run(_body(["S7"]), db)

    assert result.ya_tenian == 1
    assert result.geocodificados == 0


def test_fallback_por_ml_shipping(db: Session, monkeypatch: pytest.MonkeyPatch):
    _crear_etiqueta(db, "S8")
    _crear_ml_shipping(
        db,
        "S8",
        mlstreet_name="Corrientes",
        mlstreet_number="1234",
        mlcity_name="CABA",
        mlzip_code="1043",
    )

    async def fake_geocode(direccion, ciudad="Buenos Aires", zip_code=None, **kw):
        assert direccion == "Corrientes 1234"
        assert ciudad == "CABA"
        assert zip_code == "1043"
        return (9.0, 10.0)

    monkeypatch.setattr(mod, "geocode_address", fake_geocode)

    result = _run(_body(["S8"]), db)

    assert result.geocodificados == 1
    updated = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == "S8").first()
    assert updated.latitud == 9.0
    assert updated.longitud == 10.0


def test_etiqueta_que_lanza_excepcion_cuenta_errores_sin_abortar_el_batch(db: Session, monkeypatch: pytest.MonkeyPatch):
    _crear_etiqueta(db, "S9", direccion_completa="Calle Rota 1")
    _crear_etiqueta(db, "S10", direccion_completa="Calle Sana 2")

    async def fake_geocode(direccion, **kw):
        if direccion == "Calle Rota 1":
            raise RuntimeError("boom")
        return (11.0, 12.0)

    monkeypatch.setattr(mod, "geocode_address", fake_geocode)

    result = _run(_body(["S9", "S10"]), db)

    assert result.errores == 1
    assert result.geocodificados == 1
    assert result.total == 2


def test_sin_direccion_alguna_cuenta_sin_resultado_sin_llamar_http(db: Session, monkeypatch: pytest.MonkeyPatch):
    _crear_etiqueta(db, "S11")  # no manual, no direccion_completa, no ML shipping row

    async def fail_if_called(*a, **kw):
        raise AssertionError("no debería llamar a geocode_address: no hay dirección alguna")

    monkeypatch.setattr(mod, "geocode_address", fail_if_called)

    result = _run(_body(["S11"]), db)

    assert result.sin_resultado == 1
    assert result.geocodificados == 0
