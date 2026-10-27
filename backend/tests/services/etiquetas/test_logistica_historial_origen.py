"""`marcar_origen_logistica` (flex-logistica-historial T3, S2): sets who and source of a logistics change for the
history trigger, only for the current transaction, and does nothing off Postgres."""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services.etiquetas.logistica_historial_origen import marcar_origen_logistica
from tests.services.sell._schema import throwaway_schema

_SETTINGS = (
    "SELECT current_setting('app.logistica_usuario_id', true), current_setting('app.logistica_operador_id', true), "
    "current_setting('app.logistica_origen', true)"
)


def test_off_postgres_it_is_a_no_op(db) -> None:
    # SQLite has no set_config: calling it there would raise.
    marcar_origen_logistica(db, "asignar", usuario_id=1, operador_id=2)


@pytest.fixture()
def pg_engine_schema() -> Iterator[Engine]:
    with throwaway_schema("etq_log_origen_svc", []) as engine:
        yield engine


@pytest.mark.postgres
class TestSettings:
    def test_it_sets_the_three_settings_for_the_transaction(self, pg_engine_schema: Engine) -> None:
        with Session(bind=pg_engine_schema) as db:
            marcar_origen_logistica(db, "pistoleado", usuario_id=7, operador_id=12)

            assert tuple(db.execute(text(_SETTINGS)).one()) == ("7", "12", "pistoleado")

    def test_a_missing_id_is_left_empty(self, pg_engine_schema: Engine) -> None:
        with Session(bind=pg_engine_schema) as db:
            marcar_origen_logistica(db, "masivo", usuario_id=7)

            assert tuple(db.execute(text(_SETTINGS)).one()) == ("7", "", "masivo")

    @pytest.mark.parametrize("fin", ["commit", "rollback"])
    def test_the_settings_do_not_leak_into_a_later_transaction_of_the_same_connection(
        self, pg_engine_schema: Engine, fin: str
    ) -> None:
        """A pooled connection serves later requests: a session-level setting would credit their changes to
        this user and source."""
        with pg_engine_schema.connect() as conn, Session(bind=conn) as db:
            marcar_origen_logistica(db, "manual", usuario_id=7, operador_id=12)
            getattr(db, fin)()

            assert tuple(db.execute(text(_SETTINGS)).one()) in {("", "", ""), (None, None, None)}
