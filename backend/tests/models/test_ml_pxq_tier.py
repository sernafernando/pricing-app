"""Model tests for `MlPxqTier` (ml-wholesale-pxq-pricing PR2).

Spec coverage: tier CRUD constraints — `cantidad_minima >= 1` (CheckConstraint),
unique `(publicacion_ml_id, cantidad_minima)`, nullable `costo_envio_total` /
`ml_price_id`. Max-5-tiers-per-publication is a SERVICE-layer rule (422), not a
DB constraint, and is covered separately.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import ESTADOS_VALIDOS, MlPxqTier
from app.models.publicacion_ml import PublicacionML
from app.models.producto import ProductoERP
from app.models.usuario import AuthProvider, RolUsuario, Usuario


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_user",
        email="pxq_user@example.com",
        nombre="PxQ User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def producto(db) -> ProductoERP:
    producto = ProductoERP(item_id=90001, codigo="SKU-PXQ", descripcion="Producto PxQ", costo=1000.0)
    db.add(producto)
    db.flush()
    return producto


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA900001", item_id=producto.item_id, codigo="SKU-PXQ")
    db.add(pub)
    db.flush()
    return pub


def _make_tier(publicacion, usuario, cantidad_minima=5, **overrides):
    defaults = dict(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=cantidad_minima,
        precio_unitario=500.00,
        costo_envio_total=None,
        ml_price_id=None,
        estado="incompleto",
        usuario_id=usuario.id,
    )
    defaults.update(overrides)
    return MlPxqTier(**defaults)


def test_create_tier_row(db, publicacion, pxq_user) -> None:
    tier = _make_tier(publicacion, pxq_user)
    db.add(tier)
    db.flush()

    assert tier.id is not None
    assert tier.cantidad_minima == 5
    assert tier.costo_envio_total is None
    assert tier.ml_price_id is None
    assert tier.estado == "incompleto"
    assert tier.created_at is not None
    # NOTE: SQLite loses tzinfo after flush (known repo trap); the column
    # type itself is DateTime(timezone=True) — see the model definition.


def test_costo_envio_total_and_ml_price_id_are_nullable(db, publicacion, pxq_user) -> None:
    tier = _make_tier(publicacion, pxq_user, costo_envio_total=None, ml_price_id=None)
    db.add(tier)
    db.flush()
    assert tier.costo_envio_total is None
    assert tier.ml_price_id is None


def test_a_one_unit_row_is_accepted_because_it_is_what_turns_on_venta_para_negocios(db, publicacion, pxq_user) -> None:
    """MercadoLibre accepts `min_purchase_unit: 1` in production
    (MLA1563835240, price id 3396) even though its documentation says the value
    must be greater than 1 — and that entry is what makes the publication
    appear as "Venta para negocios". It is not a residue: it is the switch for
    the B2B shelf, so the mirror has to be able to hold it.

    The constraint that used to reject it was derived from the documentation
    alone. Reality contradicts the documentation at both ends, which is exactly
    why this row is a test and not a comment: reading the same doc again in six
    months is what would "restore" the old rule."""
    tier = _make_tier(publicacion, pxq_user, cantidad_minima=1)
    db.add(tier)
    db.flush()

    assert tier.id is not None
    assert tier.cantidad_minima == 1


def test_cantidad_minima_of_zero_or_negative_violates_check_constraint(db, publicacion, pxq_user) -> None:
    tier = _make_tier(publicacion, pxq_user, cantidad_minima=0)
    db.add(tier)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_duplicate_publicacion_cantidad_minima_violates_unique_constraint(db, publicacion, pxq_user) -> None:
    db.add(_make_tier(publicacion, pxq_user, cantidad_minima=5))
    db.flush()

    db.add(_make_tier(publicacion, pxq_user, cantidad_minima=5))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_same_cantidad_minima_allowed_across_different_publicaciones(db, producto, pxq_user) -> None:
    other_publicacion = PublicacionML(mla="MLA900002", item_id=producto.item_id, codigo="SKU-PXQ-2")
    db.add(other_publicacion)
    db.flush()

    publicacion_a = PublicacionML(mla="MLA900003", item_id=producto.item_id, codigo="SKU-PXQ-3")
    db.add(publicacion_a)
    db.flush()

    db.add(_make_tier(publicacion_a, pxq_user, cantidad_minima=5))
    db.add(_make_tier(other_publicacion, pxq_user, cantidad_minima=5))
    db.flush()

    rows = db.query(MlPxqTier).filter_by(cantidad_minima=5).all()
    assert len(rows) == 2


def test_estado_outside_the_declared_set_is_rejected(db, publicacion, pxq_user) -> None:
    """`ESTADOS_VALIDOS` documents the tier state machine, and `estado` drives
    whether a tier is priced and written to MercadoLibre. A free-text column
    would let a typo ('sincronzado') sit forever in a state no branch handles,
    on a money path — so the declared set is a database constraint, not a
    naming convention."""
    tier = MlPxqTier(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=10,
        precio_unitario=Decimal("500.00"),
        estado="sincronzado",
        usuario_id=pxq_user.id,
    )
    db.add(tier)

    with pytest.raises(IntegrityError):
        db.flush()


def test_every_declared_estado_is_accepted(db, publicacion, pxq_user) -> None:
    for index, estado in enumerate(ESTADOS_VALIDOS):
        tier = MlPxqTier(
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=10 + index,
            precio_unitario=Decimal("500.00"),
            estado=estado,
            usuario_id=pxq_user.id,
        )
        db.add(tier)
    db.flush()


def test_declared_estado_constants_match_the_check_constraint() -> None:
    """`ESTADOS_VALIDOS` mirrors a database CheckConstraint that cannot import
    it, so nothing but this test keeps the two in step. Without it the tuple is
    documentation that silently rots the first time someone edits one side."""
    constraint = next(
        c for c in MlPxqTier.__table__.constraints if getattr(c, "name", None) == "ck_ml_pxq_tier_estado_valido"
    )
    sql = str(constraint.sqltext)

    for estado in ESTADOS_VALIDOS:
        assert f"'{estado}'" in sql, f"{estado} declared in ESTADOS_VALIDOS but missing from the constraint"
    assert sql.count("'") == len(ESTADOS_VALIDOS) * 2, "constraint allows a value not declared in ESTADOS_VALIDOS"


def test_snapshot_columns_default_to_null_meaning_never_synced(db, publicacion, pxq_user) -> None:
    """NULL is the honest value for a tier ML has never confirmed: there is no
    base to have diverged from, so the write path treats it as a create rather
    than inventing agreement."""
    tier = _make_tier(publicacion, pxq_user)
    db.add(tier)
    db.flush()

    assert tier.cantidad_sincronizada is None
    assert tier.precio_sincronizado is None


def test_snapshot_columns_store_what_ml_confirmed(db, publicacion, pxq_user) -> None:
    tier = _make_tier(publicacion, pxq_user, cantidad_sincronizada=10, precio_sincronizado=Decimal("500.00"))
    db.add(tier)
    db.flush()

    assert tier.cantidad_sincronizada == 10
    assert tier.precio_sincronizado == Decimal("500.00")
