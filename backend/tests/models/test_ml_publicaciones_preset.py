"""Model tests for the Publicaciones ML presets and layouts (S4): the database itself keeps one name per owner and
view (case-insensitive), one shared name per view, one layout per user and view, and nulls a layout's remembered
preset when the preset goes away."""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.models.ml_publicaciones_preset import MlPublicacionesLayout, MlPublicacionesPreset

PAYLOAD = {"columns": {"visibility": {}, "order": []}, "params": {}}


def _preset(usuario_id: int | None, nombre: str, vista: str = "publicacion") -> MlPublicacionesPreset:
    return MlPublicacionesPreset(usuario_id=usuario_id, vista=vista, nombre=nombre, payload=PAYLOAD)


def test_personal_name_is_unique_per_owner_and_view_case_insensitive(db, active_user, admin_user):
    db.add_all(
        [
            _preset(active_user.id, "Ventas"),
            _preset(admin_user.id, "Ventas"),
            _preset(active_user.id, "Ventas", "precios"),
        ]
    )
    db.flush()

    db.add(_preset(active_user.id, "VENTAS"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_shared_name_is_unique_per_view_case_insensitive(db, active_user):
    db.add_all([_preset(None, "Equipo"), _preset(active_user.id, "Equipo")])
    db.flush()

    db.add(_preset(None, "equipo"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_one_layout_per_user_and_view(db, active_user):
    db.add(MlPublicacionesLayout(usuario_id=active_user.id, vista="publicacion"))
    db.flush()

    db.add(MlPublicacionesLayout(usuario_id=active_user.id, vista="publicacion"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_a_preset_nulls_the_layouts_remembering_it(db, active_user):
    preset = _preset(active_user.id, "Mío")
    db.add(preset)
    db.flush()
    layout = MlPublicacionesLayout(usuario_id=active_user.id, vista="publicacion", preset_activo_id=preset.id)
    db.add(layout)
    db.flush()

    db.execute(delete(MlPublicacionesPreset).where(MlPublicacionesPreset.id == preset.id))
    db.expire_all()

    assert db.get(MlPublicacionesLayout, layout.id).preset_activo_id is None
