"""Unit tests for app.services.pm_scope (sub-pm-scope-marcas PR1).

Covers the UNION dedup contract (marcas_pm ∪ marca_sub_pm), full-view bypass,
inactive-user exclusion, pm_ids role-gate, and the raw-SQL snippet builder.
"""

from __future__ import annotations

from app.core.security import get_password_hash
from app.models.marca_pm import MarcaPM
from app.models.marca_sub_pm import MarcaSubPM
from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.pm_scope import (
    FULL_VIEW_ROLES,
    aplicar_filtro_marcas_pm,
    get_pares_marca_categoria_usuario,
    get_pares_para_pm_ids,
    is_full_view,
    scope_exists_sql,
)


def _make_user(db, rol_ventas, username: str, rol=RolUsuario.VENTAS, activo: bool = True) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=rol,
        rol_id=rol_ventas.id if rol not in FULL_VIEW_ROLES else None,
        auth_provider=AuthProvider.LOCAL,
        activo=activo,
    )
    db.add(user)
    db.flush()
    return user


class TestIsFullView:
    def test_full_view_roles_return_true(self, db, rol_ventas) -> None:
        for rol in FULL_VIEW_ROLES:
            user = _make_user(db, rol_ventas, f"fv_{rol.value}", rol=rol)
            assert is_full_view(user) is True

    def test_non_full_view_role_returns_false(self, db, rol_ventas) -> None:
        user = _make_user(db, rol_ventas, "not_full_view")
        assert is_full_view(user) is False


class TestGetParesMarcaCategoriaUsuario:
    def test_full_view_user_returns_none(self, db, rol_ventas) -> None:
        user = _make_user(db, rol_ventas, "gerente_user", rol=RolUsuario.GERENTE)
        assert get_pares_marca_categoria_usuario(db, user) is None

    def test_titular_and_sub_pm_same_pair_dedup_to_one(self, db, rol_ventas) -> None:
        user = _make_user(db, rol_ventas, "dual_user")
        db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=user.id))
        db.add(MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=user.id))
        db.flush()

        pares = get_pares_marca_categoria_usuario(db, user)

        assert pares is not None
        assert pares.count(("NIKE", "ZAPATILLAS")) == 1

    def test_disjoint_titular_and_sub_pm_pairs_both_present(self, db, rol_ventas) -> None:
        titular = _make_user(db, rol_ventas, "titular_user")
        db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=titular.id))
        db.add(MarcaSubPM(marca="Adidas", categoria="Ropa", usuario_id=titular.id))
        db.flush()

        pares = get_pares_marca_categoria_usuario(db, titular)

        assert set(pares) == {("NIKE", "ZAPATILLAS"), ("ADIDAS", "ROPA")}

    def test_inactive_sub_pm_excluded_from_scope(self, db, rol_ventas) -> None:
        inactive = _make_user(db, rol_ventas, "inactive_sub_pm", activo=False)
        db.add(MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=inactive.id))
        db.flush()

        pares = get_pares_marca_categoria_usuario(db, inactive)

        assert pares == []

    def test_user_with_no_pairs_returns_empty_list(self, db, rol_ventas) -> None:
        user = _make_user(db, rol_ventas, "no_pairs_user")
        assert get_pares_marca_categoria_usuario(db, user) == []


class TestGetParesParaPmIds:
    def test_union_of_titular_and_sub_pm_across_ids(self, db, rol_ventas) -> None:
        u1 = _make_user(db, rol_ventas, "pm_ids_u1")
        u2 = _make_user(db, rol_ventas, "pm_ids_u2")
        db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=u1.id))
        db.add(MarcaSubPM(marca="Adidas", categoria="Ropa", usuario_id=u2.id))
        db.flush()

        pares = get_pares_para_pm_ids(db, [u1.id, u2.id])

        assert set(pares) == {("NIKE", "ZAPATILLAS"), ("ADIDAS", "ROPA")}

    def test_empty_pm_ids_returns_empty_list(self, db) -> None:
        assert get_pares_para_pm_ids(db, []) == []


class TestAplicarFiltroMarcasPm:
    def test_pm_ids_dropped_for_non_full_view_role(self, db, rol_ventas) -> None:
        """D2: pm_ids is full-view-role-only; a non-privileged caller's pm_ids is ignored,
        falling back to the caller's own effective scope (empty here)."""
        caller = _make_user(db, rol_ventas, "aplicar_caller")
        other = _make_user(db, rol_ventas, "aplicar_other")
        db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=other.id))
        db.flush()

        query = db.query(MLVentaMetrica)
        filtered = aplicar_filtro_marcas_pm(query, caller, db, pm_ids=str(other.id))

        # Caller has no pairs of their own -> falls back to the "no results" sentinel.
        results = filtered.all()
        assert results == []
        compiled = filtered.statement.compile(compile_kwargs={"literal_binds": True})
        assert "__NINGUNA__" in str(compiled)

    def test_full_view_role_pm_ids_honored(self, db, rol_ventas) -> None:
        gerente = _make_user(db, rol_ventas, "aplicar_gerente", rol=RolUsuario.GERENTE)
        other = _make_user(db, rol_ventas, "aplicar_other2")
        db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=other.id))
        db.flush()

        query = db.query(MLVentaMetrica)
        filtered = aplicar_filtro_marcas_pm(query, gerente, db, pm_ids=str(other.id))

        compiled = str(filtered)
        assert "__NINGUNA__" not in compiled and "NINGUNA" not in compiled

    def test_full_view_role_no_pm_ids_no_filter(self, db, rol_ventas) -> None:
        gerente = _make_user(db, rol_ventas, "aplicar_gerente2", rol=RolUsuario.GERENTE)
        query = db.query(MLVentaMetrica)
        filtered = aplicar_filtro_marcas_pm(query, gerente, db)
        assert filtered is query or str(filtered) == str(query)


class TestAplicarFiltroMarcasPmColumnasGenericas:
    """The filter accepts marca_col/categoria_col to scope a non-MLVentaMetrica
    query (e.g. a ProductoERP catalog search) with the same effective-scope rules."""

    def test_scopes_productoerp_query_to_user_pairs(self, db, rol_ventas) -> None:
        from app.models.producto import ProductoERP

        pm = _make_user(db, rol_ventas, "pe_scope_pm")
        db.add(MarcaPM(marca="Lenovo", categoria="Notebooks", usuario_id=pm.id))
        db.add(ProductoERP(item_id=990001, codigo="EAN-LEN-1069", marca="Lenovo", categoria="Notebooks", activo=True))
        db.add(ProductoERP(item_id=990002, codigo="EAN-HP-1069", marca="HP", categoria="Notebooks", activo=True))
        db.flush()

        query = db.query(ProductoERP)
        filtered = aplicar_filtro_marcas_pm(
            query, pm, db, marca_col=ProductoERP.marca, categoria_col=ProductoERP.categoria
        )
        item_ids = {r.item_id for r in filtered.all()}

        assert 990001 in item_ids  # Lenovo/Notebooks — within the PM's scope
        assert 990002 not in item_ids  # HP/Notebooks — outside the PM's scope

    def test_full_view_user_sees_all_productoerp(self, db, rol_ventas) -> None:
        from app.models.producto import ProductoERP

        gerente = _make_user(db, rol_ventas, "pe_scope_gerente", rol=RolUsuario.GERENTE)
        db.add(ProductoERP(item_id=990003, codigo="EAN-ANY-1069", marca="CualquierMarca", categoria="X", activo=True))
        db.flush()

        query = db.query(ProductoERP).filter(ProductoERP.item_id == 990003)
        filtered = aplicar_filtro_marcas_pm(
            query, gerente, db, marca_col=ProductoERP.marca, categoria_col=ProductoERP.categoria
        )
        assert {r.item_id for r in filtered.all()} == {990003}


class TestScopeExistsSql:
    def test_contains_both_tables_and_scope_user_id_param(self) -> None:
        snippet = scope_exists_sql("pe")
        assert "marcas_pm" in snippet
        assert "marca_sub_pm" in snippet
        assert ":scope_user_id" in snippet
        assert "pe.marca" in snippet
        assert "pe.categoria" in snippet

    def test_custom_alias_is_used(self) -> None:
        snippet = scope_exists_sql("x")
        assert "x.marca" in snippet
        assert "x.categoria" in snippet
