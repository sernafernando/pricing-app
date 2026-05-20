"""
T2.3 — Model test for F2: NotaCreditoLocal has tipo column.

Verifies that the SQLAlchemy model has the new F2 column before testing
service logic.
"""

from __future__ import annotations

from sqlalchemy import inspect as sa_inspect, String

from app.models.nota_credito_local import NotaCreditoLocal


class TestNotaCreditoLocalModelF2:
    """T2.3 — NotaCreditoLocal has tipo String(8) NOT NULL default 'credito'."""

    def test_has_tipo_column(self) -> None:
        mapper = sa_inspect(NotaCreditoLocal)
        col_names = [col.key for col in mapper.columns]
        assert "tipo" in col_names, "NotaCreditoLocal should have 'tipo' column"

    def test_tipo_is_string(self) -> None:
        mapper = sa_inspect(NotaCreditoLocal)
        col = mapper.columns["tipo"]
        assert isinstance(col.type, String), f"Expected String, got {type(col.type)}"

    def test_tipo_not_nullable(self) -> None:
        mapper = sa_inspect(NotaCreditoLocal)
        col = mapper.columns["tipo"]
        assert col.nullable is False, "tipo should be NOT NULL"

    def test_tipo_default_is_credito(self) -> None:
        mapper = sa_inspect(NotaCreditoLocal)
        col = mapper.columns["tipo"]
        # server_default is the DB-level default; default is the Python-level default.
        server_default = col.server_default
        python_default = col.default
        has_credito_server_default = server_default is not None and "credito" in str(server_default.arg)
        has_credito_python_default = python_default is not None and python_default.arg == "credito"
        assert has_credito_server_default or has_credito_python_default, (
            "tipo should default to 'credito' (server_default or python default)"
        )
