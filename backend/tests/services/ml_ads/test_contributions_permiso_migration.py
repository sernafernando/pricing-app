"""ml-ads-brand-contribution T1b -- `ml_metricas.gestionar_aportes_ads` is seeded for ADMIN only and removed on
downgrade (overrides included). Runs in a throwaway Postgres schema next to bare stand-ins of the permission tables."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from tests.services.ml_ads.test_account_level_migration import _script_directory
from tests.services.ml_ads.test_contributions_migration import run_migration, throwaway_schema

REVISION = "20261114_ml_ads_contributions_permiso"
_PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{REVISION}.py"
_STUBS = [
    "CREATE TABLE roles (id SERIAL PRIMARY KEY, codigo VARCHAR(50) UNIQUE)",
    "CREATE TABLE permisos (id SERIAL PRIMARY KEY, codigo VARCHAR(100) UNIQUE, nombre TEXT, descripcion TEXT, "
    "categoria TEXT, orden INTEGER, es_critico BOOLEAN, created_at TIMESTAMPTZ)",
    "CREATE TABLE roles_permisos_base (rol_id INTEGER, permiso_id INTEGER, PRIMARY KEY (rol_id, permiso_id))",
    "CREATE TABLE usuarios_permisos_override (usuario_id INTEGER, permiso_id INTEGER)",
    "INSERT INTO roles (codigo) VALUES ('ADMIN'), ('GERENTE')",
]
_GRANTED = (
    "SELECT r.codigo, p.codigo FROM roles_permisos_base rp JOIN roles r ON r.id = rp.rol_id "
    "JOIN permisos p ON p.id = rp.permiso_id"
)


def _build(eng) -> None:
    with eng.begin() as conn:
        for statement in _STUBS:
            conn.execute(text(statement))
    run_migration(eng, "upgrade", _PATH)


def test_one_parent_and_an_ancestor_of_the_single_head() -> None:
    script = _script_directory()
    assert script.get_revision(REVISION).down_revision == "20261113_ml_ads_campaign_contributions"
    [head] = script.get_heads()
    assert REVISION in {r.revision for r in script.walk_revisions(base="base", head=head)}


@pytest.mark.postgres
def test_seeded_for_admin_only_and_removed_on_downgrade() -> None:
    with throwaway_schema(_build) as eng:
        with eng.begin() as conn:
            assert [tuple(r) for r in conn.execute(text(_GRANTED))] == [("ADMIN", "ml_metricas.gestionar_aportes_ads")]
            conn.execute(text("INSERT INTO usuarios_permisos_override SELECT 7, id FROM permisos"))
        run_migration(eng, "downgrade", _PATH)
        with eng.connect() as conn:
            for table in ("permisos", "roles_permisos_base", "usuarios_permisos_override"):
                assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, table
