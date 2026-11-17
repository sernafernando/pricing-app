"""Mass undo of logistics changes (flex-deshacer-masivo S2, S3, S5).

S2: `POST /etiquetas-envio/deshacer-logistica-masivo` undoes the last change of each selected label with the same
rule as the single undo, and reports how many were reverted and why the others were not.

S3: `GET /etiquetas-envio/operaciones-masivas-logistica` lists the latest bulk assignments (one per transaction of
`asignar-masivo`: same origen "masivo", user, timestamp and target logistics) and
`POST /etiquetas-envio/operaciones-masivas-logistica/{operacion_id}/deshacer` reverts a whole one, skipping and
reporting labels that changed after it.

Same throwaway Postgres schema and real history trigger as the single undo tests.
"""

from __future__ import annotations

from typing import Optional

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.api.endpoints import etiquetas_assignments, etiquetas_shared
from tests.api import test_etiquetas_logistica_historial_ui_postgres as base
from tests.api.test_etiquetas_logistica_historial_ui_postgres import (
    _DOS,
    _OPERADOR_ID,
    _UNO,
    _USUARIO_ID,
    _cambiar,
    _historial,
    _logistica_actual,
    _user,
)

# Same throwaway schema, seed and real trigger as the single undo tests.
engine = base.engine
db = base.db
publicados = base.publicados

_OTRO_USUARIO_ID = 8

_CAMBIO_POSTERIOR = "La etiqueta cambió de logística después de esta operación."
_NO_EXISTE = "La etiqueta no existe."
_SIN_CAMBIOS = "La etiqueta no tiene cambios de logística para deshacer."
_ANTERIOR_INACTIVA = "La logística anterior está inactiva."
_CAMBIO_SIN_REGISTRO = "La logística cambió desde el último registro; recargá el historial."


def _etiquetas(engine: Engine, *filas: tuple[str, Optional[int]]) -> None:
    with engine.begin() as conn:
        for shipping_id, logistica_id in filas:
            conn.execute(
                text(
                    "INSERT INTO etiquetas_envio (shipping_id, fecha_envio, logistica_id, es_manual) "
                    "VALUES (:s, '2026-10-27', :l, false)"
                ),
                {"s": shipping_id, "l": logistica_id},
            )
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO usuarios (id, nombre, activo) VALUES ({_OTRO_USUARIO_ID}, 'Beto', true)"))


def _masivo(db: Session, shipping_ids: list[str], logistica_id: int, usuario_id: int = _USUARIO_ID) -> dict:
    user = _user()
    user.id = usuario_id
    payload = etiquetas_shared.AsignarMasivoRequest(shipping_ids=shipping_ids, logistica_id=logistica_id)
    return etiquetas_assignments.asignar_masivo(payload, db=db, current_user=user)


def _deshacer_seleccion(db: Session, shipping_ids: list[str], operador_id: Optional[int] = None) -> dict:
    payload = etiquetas_shared.DeshacerLogisticaMasivoRequest(shipping_ids=shipping_ids, operador_id=operador_id)
    return etiquetas_assignments.deshacer_logistica_masivo(payload, db=db, current_user=_user()).model_dump()


def _operaciones(db: Session) -> list[dict]:
    return [op.model_dump() for op in etiquetas_assignments.operaciones_masivas_logistica(db=db, current_user=_user())]


def _deshacer_operacion(db: Session, operacion_id: int) -> dict:
    return etiquetas_assignments.deshacer_operacion_masiva_logistica(
        operacion_id, payload=None, db=db, current_user=_user()
    ).model_dump()


def _motivos(respuesta: dict) -> dict[str, list[str]]:
    return {m["motivo"]: sorted(m["shipping_ids"]) for m in respuesta["no_revertidas_por_motivo"]}


@pytest.mark.postgres
class TestDeshacerSeleccion:
    def test_each_label_goes_back_to_the_logistica_before_its_own_last_change(
        self, engine: Engine, db: Session, publicados: list
    ) -> None:
        _etiquetas(engine, ("A", 2), ("B", None))
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)  # S1: 1 -> 2
        _cambiar(engine, "A", 3, "pistoleado", operador_id=_OPERADOR_ID)  # A: 2 -> 3
        _cambiar(engine, "B", 1, "masivo", usuario_id=_USUARIO_ID)  # B: None -> 1

        respuesta = _deshacer_seleccion(db, ["S1", "A", "B"], operador_id=_OPERADOR_ID)

        assert (respuesta["revertidas"], respuesta["no_revertidas"], respuesta["no_revertidas_por_motivo"]) == (
            3,
            0,
            [],
        )
        assert [_logistica_actual(engine, s) for s in ("S1", "A", "B")] == [1, 2, None]
        assert _historial(engine, "A")[-1] == (3, 2, _USUARIO_ID, _OPERADOR_ID, "deshacer")
        assert publicados == [("etiquetas:changed", {"hint": "reload"})]

    def test_reports_the_labels_it_could_not_undo_grouped_by_reason(self, engine: Engine, db: Session) -> None:
        _etiquetas(engine, ("A", 2), ("B", 1))
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)  # revertible
        _cambiar(engine, "S3", 1, "asignar", usuario_id=_USUARIO_ID)  # back to inactive 4
        with engine.begin() as conn:  # B out of step with its last record
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 3 WHERE shipping_id = 'B'"))
            conn.execute(text("ALTER TABLE etiquetas_envio DISABLE TRIGGER trg_etiquetas_envio_logistica_historial"))
            conn.execute(text("UPDATE etiquetas_envio SET logistica_id = 2 WHERE shipping_id = 'B'"))
            conn.execute(text("ALTER TABLE etiquetas_envio ENABLE TRIGGER trg_etiquetas_envio_logistica_historial"))

        respuesta = _deshacer_seleccion(db, ["S1", "S3", "A", "B", "NOPE"])

        assert (respuesta["revertidas"], respuesta["no_revertidas"]) == (1, 4)
        assert _motivos(respuesta) == {
            _ANTERIOR_INACTIVA: ["S3"],
            _SIN_CAMBIOS: ["A"],
            _CAMBIO_SIN_REGISTRO: ["B"],
            _NO_EXISTE: ["NOPE"],
        }
        assert [_logistica_actual(engine, s) for s in ("S1", "S3", "A", "B")] == [1, 1, 2, 2]

    def test_nothing_to_undo_changes_nothing_and_publishes_nothing(
        self, engine: Engine, db: Session, publicados: list
    ) -> None:
        respuesta = _deshacer_seleccion(db, ["S1"])

        assert (respuesta["revertidas"], _motivos(respuesta)) == (0, {_SIN_CAMBIOS: ["S1"]})
        assert (_logistica_actual(engine, "S1"), _historial(engine, "S1"), publicados) == (1, [], [])

    def test_unknown_operador_is_404_and_changes_nothing(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)

        with pytest.raises(HTTPException) as exc:
            _deshacer_seleccion(db, ["S1"], operador_id=_OPERADOR_ID + 999)

        assert exc.value.status_code == 404
        assert _logistica_actual(engine, "S1") == 2


@pytest.mark.postgres
class TestOperacionesMasivas:
    def test_lists_each_bulk_assignment_newest_first_with_who_when_target_and_count(
        self, engine: Engine, db: Session
    ) -> None:
        _etiquetas(engine, ("A", None), ("B", None), ("C", 1))
        _masivo(db, ["A", "B", "C"], 2)  # changes A, B, C
        _masivo(db, ["S1", "C"], 1, usuario_id=_OTRO_USUARIO_ID)  # changes S1? no (already 1); C: 2 -> 1
        _cambiar(engine, "A", 3, "asignar", usuario_id=_USUARIO_ID)  # not a bulk op

        operaciones = _operaciones(db)

        assert [(o["usuario_nombre"], o["logistica"], o["etiquetas"]) for o in operaciones] == [
            ("Beto", _UNO, 1),
            ("Ana Panel", _DOS, 3),
        ]
        assert operaciones[0]["cambiado_en"] > operaciones[1]["cambiado_en"]
        assert all(isinstance(o["id"], int) for o in operaciones)

    def test_undo_reverts_the_whole_operation_to_each_previous_logistica(
        self, engine: Engine, db: Session, publicados: list
    ) -> None:
        _etiquetas(engine, ("A", None), ("B", 3))
        _masivo(db, ["S1", "A", "B"], 2)
        operacion = _operaciones(db)[0]
        publicados.clear()

        respuesta = _deshacer_operacion(db, operacion["id"])

        assert (respuesta["revertidas"], respuesta["no_revertidas"]) == (3, 0)
        assert [_logistica_actual(engine, s) for s in ("S1", "A", "B")] == [1, None, 3]
        assert _historial(engine, "B")[-1] == (2, 3, _USUARIO_ID, None, "deshacer")
        assert publicados == [("etiquetas:changed", {"hint": "reload"})]
        # The undo is not a bulk assignment: the list does not grow.
        assert [o["id"] for o in _operaciones(db)] == [operacion["id"]]

    def test_a_label_changed_after_the_operation_is_skipped_and_reported(self, engine: Engine, db: Session) -> None:
        _etiquetas(engine, ("A", None), ("B", None))
        _masivo(db, ["A", "B"], 2)
        operacion = _operaciones(db)[0]
        _cambiar(engine, "B", 3, "pistoleado", operador_id=_OPERADOR_ID)  # B changed afterwards

        respuesta = _deshacer_operacion(db, operacion["id"])

        assert (respuesta["revertidas"], _motivos(respuesta)) == (1, {_CAMBIO_POSTERIOR: ["B"]})
        assert (_logistica_actual(engine, "A"), _logistica_actual(engine, "B")) == (None, 3)

    def test_a_label_undone_back_to_the_operation_value_is_still_not_reverted(
        self, engine: Engine, db: Session
    ) -> None:
        # B goes 2 -> 3 -> 2 after the bulk op: it holds the op's value again but its last change is not the op.
        _etiquetas(engine, ("B", None))
        _masivo(db, ["B"], 2)
        operacion = _operaciones(db)[0]
        _cambiar(engine, "B", 3, "asignar", usuario_id=_USUARIO_ID)
        _cambiar(engine, "B", 2, "asignar", usuario_id=_USUARIO_ID)

        respuesta = _deshacer_operacion(db, operacion["id"])

        assert (respuesta["revertidas"], _motivos(respuesta)) == (0, {_CAMBIO_POSTERIOR: ["B"]})
        assert _logistica_actual(engine, "B") == 2

    def test_undoing_one_operation_leaves_another_users_simultaneous_one_alone(
        self, engine: Engine, db: Session
    ) -> None:
        _etiquetas(engine, ("A", None), ("B", None))
        _masivo(db, ["A"], 2)
        _masivo(db, ["B"], 2, usuario_id=_OTRO_USUARIO_ID)
        de_ana = next(o for o in _operaciones(db) if o["usuario_nombre"] == "Ana Panel")

        _deshacer_operacion(db, de_ana["id"])

        assert (_logistica_actual(engine, "A"), _logistica_actual(engine, "B")) == (None, 2)

    def test_previous_logistica_inactive_is_skipped_and_reported(self, engine: Engine, db: Session) -> None:
        _masivo(db, ["S3"], 2)  # S3 was on inactive 4

        respuesta = _deshacer_operacion(db, _operaciones(db)[0]["id"])

        assert (respuesta["revertidas"], _motivos(respuesta)) == (0, {_ANTERIOR_INACTIVA: ["S3"]})
        assert _logistica_actual(engine, "S3") == 2

    def test_an_id_that_is_not_a_bulk_operation_is_404(self, engine: Engine, db: Session) -> None:
        _cambiar(engine, "S1", 2, "asignar", usuario_id=_USUARIO_ID)
        with engine.connect() as conn:
            fila_asignar = conn.execute(text("SELECT id FROM etiquetas_envio_logistica_historial")).scalar()

        for operacion_id in (fila_asignar, 999_999):
            with pytest.raises(HTTPException) as exc:
                _deshacer_operacion(db, operacion_id)
            assert exc.value.status_code == 404


def _con_a_designar(engine: Engine) -> int:
    """The placeholder logística as production has it: an ordinary active row named 'A DESIGNAR'."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO logisticas (id, nombre, activa, color, pistoleado_asigna) "
                "VALUES (5, 'A DESIGNAR', true, NULL, false)"
            )
        )
    return 5


def _conflictos(db: Session, shipping_ids: list[str], logistica_id: int) -> dict:
    payload = etiquetas_shared.AsignarMasivoRequest(shipping_ids=shipping_ids, logistica_id=logistica_id)
    return etiquetas_assignments.conflictos_asignar_masivo(payload, db=db, current_user=_user())


def _masivo_solo_sin(db: Session, shipping_ids: list[str], logistica_id: int) -> dict:
    payload = etiquetas_shared.AsignarMasivoRequest(
        shipping_ids=shipping_ids, logistica_id=logistica_id, solo_sin_logistica=True
    )
    return etiquetas_assignments.asignar_masivo(payload, db=db, current_user=_user())


@pytest.mark.postgres
class TestSobrescritura:
    def test_counts_labels_that_would_lose_another_logistica(self, engine: Engine, db: Session) -> None:
        a_designar = _con_a_designar(engine)
        _etiquetas(engine, ("A", 2), ("B", a_designar), ("C", 3))
        # S1 on 1 (other), S2 NULL, S3 on inactive 4 (other), A already on 2, B on the placeholder, C on 3 (other).

        assert _conflictos(db, ["S1", "S2", "S3", "A", "B", "C", "NOPE"], 2) == {"sobrescribiria": 3}

    def test_a_designar_counts_as_without_logistica(self, engine: Engine, db: Session) -> None:
        a_designar = _con_a_designar(engine)
        _etiquetas(engine, ("B", a_designar))

        assert _conflictos(db, ["B"], 2) == {"sobrescribiria": 0}

    def test_only_without_logistica_changes_null_and_a_designar_and_reports_skipped(
        self, engine: Engine, db: Session
    ) -> None:
        a_designar = _con_a_designar(engine)
        _etiquetas(engine, ("A", 2), ("B", a_designar))

        respuesta = _masivo_solo_sin(db, ["S1", "S2", "A", "B"], 2)

        assert (respuesta["actualizadas"], respuesta["salteadas"]) == (2, 1)
        assert [_logistica_actual(engine, s) for s in ("S1", "S2", "A", "B")] == [1, 2, 2, 2]

    def test_default_still_overwrites_everything(self, engine: Engine, db: Session) -> None:
        _etiquetas(engine, ("A", 3))

        respuesta = _masivo(db, ["S1", "S2", "A"], 2)

        assert (respuesta["actualizadas"], respuesta["salteadas"]) == (3, 0)
        assert [_logistica_actual(engine, s) for s in ("S1", "S2", "A")] == [2, 2, 2]

    def test_the_bulk_assignment_of_only_without_logistica_is_undoable_as_one_operation(
        self, engine: Engine, db: Session
    ) -> None:
        _masivo_solo_sin(db, ["S1", "S2"], 2)

        operacion = _operaciones(db)[0]

        assert operacion["etiquetas"] == 1
        assert _deshacer_operacion(db, operacion["id"])["revertidas"] == 1
        assert _logistica_actual(engine, "S2") is None


@pytest.mark.parametrize(
    "nombre, es",
    [
        ("A DESIGNAR", True),
        ("a designar", True),
        ("  A   Designár ", True),
        ("A designar 2", False),
        ("Designar", False),
        (None, False),
    ],
)
def test_a_designar_is_recognized_by_normalized_name(nombre: Optional[str], es: bool) -> None:
    from app.services.etiquetas.logistica_a_designar import es_a_designar

    assert es_a_designar(nombre) is es


@pytest.mark.postgres
class TestPermiso:
    @pytest.mark.parametrize(
        "llamar",
        [
            lambda db: _deshacer_seleccion(db, ["S1"]),
            lambda db: _operaciones(db),
            lambda db: _deshacer_operacion(db, 1),
            lambda db: _conflictos(db, ["S1"], 2),
        ],
        ids=["deshacer-seleccion", "operaciones", "deshacer-operacion", "conflictos"],
    )
    def test_requires_asignar_logistica(self, engine: Engine, db: Session, monkeypatch, llamar) -> None:
        pedidos: list[str] = []

        def sin_permiso(_db, _user, codigo: str) -> bool:
            pedidos.append(codigo)
            return False

        monkeypatch.setattr(etiquetas_shared, "verificar_permiso", sin_permiso)

        with pytest.raises(HTTPException) as exc:
            llamar(db)

        assert (exc.value.status_code, pedidos) == (403, ["envios_flex.asignar_logistica"])
