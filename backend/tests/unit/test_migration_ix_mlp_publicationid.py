"""ODD `metricas-ml-tablero` T1: the store filter's MLA -> store lookup rides
an index on `tb_mercadolibre_items_publicados.mlp_publicationid`, created by
its own migration under the SAME name the model's `index=True` produces."""

from __future__ import annotations

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261001_ix_mlp_publicationid"
_INDEX = "ix_tb_mercadolibre_items_publicados_mlp_publicationid"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def test_the_graph_has_a_single_head_containing_this_revision() -> None:
    script = _script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic forked: {heads}"
    assert any(rev.revision == _REVISION for rev in script.walk_revisions("base", heads[0]))


def test_the_migration_creates_the_index_the_model_declares() -> None:
    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

    module = _script_directory().get_revision(_REVISION).module
    assert module.INDEX == _INDEX
    assert _INDEX in {ix.name for ix in MercadoLibreItemPublicado.__table__.indexes}
