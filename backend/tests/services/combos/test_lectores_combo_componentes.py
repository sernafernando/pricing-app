"""Readers of the combo bill of materials use the app-owned `combo_componentes`,
not the ERP mirror `tb_item_association` (combos-propios C2).

Every test seeds the two tables with DIFFERENT compositions: the mirror holds a
stale component (700) the app table no longer has, and lacks one (600) the app
table has. A reader still on the mirror answers with 700 and without 600.
Mirror rows use the shape of `tests/scripts/test_backfill_costo_congelado.py`.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.core.security import get_password_hash
from app.models.combo_componente import ComboComponente
from app.models.prearmado import Prearmado
from app.models.rol import Rol
from app.models.tb_item import TBItem
from app.models.tb_item_association import TbItemAssociation
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.routers import prearmado as prearmado_router
from app.schemas.prearmado import PrearmadoCreate
from app.scripts.report_prearmado_ghost_serials import _bom_actual_por_combo, reportar
from app.services.combos.componentes import (
    DETALLE_COMBOS_NO_SINCRONIZADOS,
    CombosNoSincronizados,
    combos_disponibles,
    combos_que_contienen,
    componentes_de,
    es_combo,
    sql_no_es_combo,
)

COMBO = 100
SOLO_ESPEJO = 300  # a combo only the ERP mirror still lists
NUEVO = 200  # a combo only the app table has


@pytest.fixture()
def bom(db):
    for item_id, code in [
        (COMBO, "NB-COMBO-WH"),
        (NUEVO, "NUEVO"),
        (SOLO_ESPEJO, "VIEJO"),
        (500, "DISCO"),
        (600, "RAM"),
        (700, "GHOST"),
    ]:
        db.add(TBItem(comp_id=1, item_id=item_id, item_code=code, item_desc=f"desc {code}", item_expser=item_id != 600))
    db.add_all(
        [
            ComboComponente(combo_item_id=COMBO, componente_item_id=500, cantidad=Decimal("2")),
            ComboComponente(combo_item_id=COMBO, componente_item_id=600, cantidad=Decimal("1")),
            ComboComponente(combo_item_id=NUEVO, componente_item_id=600, cantidad=Decimal("1")),
        ]
    )
    db.add_all(
        [
            TbItemAssociation(comp_id=1, itema_id=1, item_id=COMBO, item_id_1=500, iasso_qty=2),
            TbItemAssociation(comp_id=1, itema_id=2, item_id=COMBO, item_id_1=700, iasso_qty=1),
            TbItemAssociation(comp_id=1, itema_id=3, item_id=SOLO_ESPEJO, item_id_1=500, iasso_qty=1),
        ]
    )
    db.flush()
    return db


class TestAccessor:
    def test_componentes_de(self, bom) -> None:
        assert componentes_de(bom, [COMBO, SOLO_ESPEJO, 999]) == {COMBO: {500: Decimal("2"), 600: Decimal("1")}}
        assert componentes_de(bom, []) == {}

    def test_es_combo(self, bom) -> None:
        assert es_combo(bom, COMBO) is True
        assert es_combo(bom, SOLO_ESPEJO) is False
        assert es_combo(bom, 500) is False

    def test_combos_que_contienen(self, bom) -> None:
        assert combos_que_contienen(bom, [500, 600, 700]) == {500: {COMBO}, 600: {COMBO, NUEVO}}
        assert combos_que_contienen(bom, []) == {}

    def test_sql_no_es_combo(self, bom) -> None:
        rows = bom.execute(
            text(f"SELECT ti.item_id FROM tb_item ti WHERE {sql_no_es_combo('ti.item_id')} ORDER BY ti.item_id")
        ).scalars()
        assert list(rows) == [SOLO_ESPEJO, 500, 600, 700]  # neither COMBO nor NUEVO


class TestPrearmadoComponentes:
    def test_lists_the_app_table_components(self, bom) -> None:
        out = prearmado_router.obtener_componentes_para_prearmado(COMBO, db=bom)

        assert [(c.item_id, c.cantidad_esperada, c.requiere_serie) for c in out.componentes] == [
            (500, 2, True),
            (600, 1, False),
        ]
        assert out.componentes[1].item_code == "RAM"
        assert out.incluye_windows == "home"

    def test_a_combo_only_the_mirror_lists_is_not_a_combo(self, bom) -> None:
        with pytest.raises(HTTPException) as exc:
            prearmado_router.obtener_componentes_para_prearmado(SOLO_ESPEJO, db=bom)
        assert exc.value.status_code == 400

    def test_reads_combo_and_components_from_the_bom_company(self, db) -> None:
        # The same item ids under another company, inserted first so an unscoped
        # lookup would pick them.
        for item_id in (COMBO, 500, 600):
            db.add(TBItem(comp_id=2, item_id=item_id, item_code=f"OTRA-{item_id}", item_desc="otra empresa"))
        db.flush()
        for item_id, code in [(COMBO, "NB-COMBO-WH"), (500, "DISCO"), (600, "RAM")]:
            db.add(
                TBItem(comp_id=1, item_id=item_id, item_code=code, item_desc=f"desc {code}", item_expser=item_id != 600)
            )
        db.add_all(
            [
                ComboComponente(combo_item_id=COMBO, componente_item_id=500, cantidad=Decimal("2")),
                ComboComponente(combo_item_id=COMBO, componente_item_id=600, cantidad=Decimal("1")),
            ]
        )
        db.flush()

        out = prearmado_router.obtener_componentes_para_prearmado(COMBO, db=db)

        assert [c.item_code for c in out.componentes] == ["DISCO", "RAM"]
        assert out.incluye_windows == "home"


class TestCrearPrearmado:
    @pytest.fixture()
    def usuario(self, db) -> Usuario:
        rol = Rol(codigo="PREARMADO_T", nombre="Prearmado", es_sistema=False, orden=90, activo=True)
        db.add(rol)
        db.flush()
        user = Usuario(
            username="prearmado_user",
            email="prearmado@example.com",
            nombre="Prearmado User",
            password_hash=get_password_hash("Pass123!"),
            rol=RolUsuario.VENTAS,
            rol_id=rol.id,
            auth_provider=AuthProvider.LOCAL,
            activo=True,
        )
        db.add(user)
        db.flush()
        return user

    def _crear(self, db, combo_item_id: int, usuario: Usuario):
        with patch.object(prearmado_router, "generar_codigo_prearmado", return_value="PRA-TEST-000001"):
            return prearmado_router.crear_prearmado(
                PrearmadoCreate(combo_item_id=combo_item_id), db=db, current_user=SimpleNamespace(id=usuario.id)
            )

    def test_creates_for_a_combo_of_the_app_table(self, bom, usuario) -> None:
        detalle = self._crear(bom, NUEVO, usuario)

        assert detalle.combo_item_id == NUEVO
        assert bom.query(Prearmado).filter_by(combo_item_id=NUEVO).count() == 1

    def test_refuses_a_combo_only_the_mirror_lists(self, bom, usuario) -> None:
        with pytest.raises(HTTPException) as exc:
            self._crear(bom, SOLO_ESPEJO, usuario)
        assert exc.value.status_code == 400


class TestReporteSerialesFantasma:
    def test_current_bom_comes_from_the_app_table(self, bom) -> None:
        assert _bom_actual_por_combo(bom, COMBO) == {500: 2.0, 600: 1.0}
        assert _bom_actual_por_combo(bom, SOLO_ESPEJO) == {}


@pytest.fixture()
def bom_vacia(db):
    """The sync never ran: the ERP mirror has the combo, the app table is empty."""
    for item_id, code in [(COMBO, "NB-COMBO-WH"), (500, "DISCO")]:
        db.add(TBItem(comp_id=1, item_id=item_id, item_code=code, item_desc=f"desc {code}"))
    db.add(TbItemAssociation(comp_id=1, itema_id=1, item_id=COMBO, item_id_1=500, iasso_qty=1))
    db.flush()
    return db


class TestEmptyBomFailsClosed:
    """An empty `combo_componentes` means "not synced yet", never "no combos":
    answering would call every real combo a plain item."""

    def test_combos_disponibles(self, bom_vacia) -> None:
        assert combos_disponibles(bom_vacia) is False
        bom_vacia.add(ComboComponente(combo_item_id=COMBO, componente_item_id=500, cantidad=Decimal("1")))
        bom_vacia.flush()
        assert combos_disponibles(bom_vacia) is True

    def test_prearmado_componentes_is_503(self, bom_vacia) -> None:
        with pytest.raises(HTTPException) as exc:
            prearmado_router.obtener_componentes_para_prearmado(COMBO, db=bom_vacia)
        assert exc.value.status_code == 503
        assert exc.value.detail == DETALLE_COMBOS_NO_SINCRONIZADOS

    def test_crear_prearmado_is_503(self, bom_vacia) -> None:
        with patch.object(prearmado_router, "generar_codigo_prearmado", return_value="PRA-TEST-000001"):
            with pytest.raises(HTTPException) as exc:
                prearmado_router.crear_prearmado(
                    PrearmadoCreate(combo_item_id=COMBO), db=bom_vacia, current_user=SimpleNamespace(id=1)
                )
        assert exc.value.status_code == 503
        assert bom_vacia.query(Prearmado).count() == 0

    def test_ghost_serial_report_refuses(self, bom_vacia) -> None:
        with pytest.raises(CombosNoSincronizados):
            reportar(bom_vacia)

    def test_ghost_serial_report_main_exits_with_an_error(self, bom_vacia, capsys) -> None:
        from app.scripts import report_prearmado_ghost_serials as script

        with (
            patch.object(script, "SessionLocal", return_value=bom_vacia),
            patch.object(bom_vacia, "close"),
            patch("sys.argv", ["report_prearmado_ghost_serials"]),
        ):
            with pytest.raises(SystemExit) as exc:
                script.main()
        assert exc.value.code != 0
        assert "combos" in str(exc.value.code)
