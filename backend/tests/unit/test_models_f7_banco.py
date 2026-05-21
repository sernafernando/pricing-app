"""
T2.1 — Model tests for F7/PR#2a: BancoEmpresa gains saldo_actual + empresa_id;
new BancoMovimiento model.
"""

from __future__ import annotations


from sqlalchemy import CheckConstraint, inspect as sa_inspect, Integer, Numeric

from app.models.banco_empresa import BancoEmpresa


class TestBancoEmpresaModelF7:
    """BancoEmpresa has saldo_actual and empresa_id columns."""

    def test_has_saldo_actual_column(self) -> None:
        mapper = sa_inspect(BancoEmpresa)
        col_names = [col.key for col in mapper.columns]
        assert "saldo_actual" in col_names, "BancoEmpresa should have 'saldo_actual' column"

    def test_saldo_actual_is_numeric(self) -> None:
        mapper = sa_inspect(BancoEmpresa)
        col = mapper.columns["saldo_actual"]
        assert isinstance(col.type, Numeric), f"Expected Numeric, got {type(col.type)}"

    def test_saldo_actual_not_nullable(self) -> None:
        mapper = sa_inspect(BancoEmpresa)
        col = mapper.columns["saldo_actual"]
        assert col.nullable is False, "saldo_actual should be NOT NULL"

    def test_has_empresa_id_column(self) -> None:
        mapper = sa_inspect(BancoEmpresa)
        col_names = [col.key for col in mapper.columns]
        assert "empresa_id" in col_names, "BancoEmpresa should have 'empresa_id' column"

    def test_empresa_id_is_integer(self) -> None:
        mapper = sa_inspect(BancoEmpresa)
        col = mapper.columns["empresa_id"]
        assert isinstance(col.type, Integer), f"Expected Integer, got {type(col.type)}"

    def test_empresa_id_is_nullable(self) -> None:
        mapper = sa_inspect(BancoEmpresa)
        col = mapper.columns["empresa_id"]
        assert col.nullable is True, "empresa_id should be nullable (AD-13)"


class TestBancoMovimientoModel:
    """BancoMovimiento model exists with required columns and constraints."""

    def test_model_importable(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        assert BancoMovimiento is not None

    def test_has_banco_id_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "banco_id" in col_names

    def test_has_fecha_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "fecha" in col_names

    def test_has_detalle_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "detalle" in col_names

    def test_has_tipo_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "tipo" in col_names

    def test_has_monto_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "monto" in col_names

    def test_has_saldo_posterior_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "saldo_posterior" in col_names

    def test_has_origen_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "origen" in col_names

    def test_has_registrado_por_id_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "registrado_por_id" in col_names

    def test_has_observaciones_column(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        mapper = sa_inspect(BancoMovimiento)
        col_names = [col.key for col in mapper.columns]
        assert "observaciones" in col_names

    def test_monto_check_constraint_present(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        table = BancoMovimiento.__table__
        check_names = [c.name for c in table.constraints if isinstance(c, CheckConstraint)]
        assert any("monto" in (n or "") for n in check_names), f"Expected a monto check constraint, got: {check_names}"

    def test_tipo_check_constraint_present(self) -> None:
        from app.models.banco_movimiento import BancoMovimiento  # noqa: PLC0415

        table = BancoMovimiento.__table__
        # The tipo CHECK is expressed as a string in the constraint sqltext
        constraints_sql = [str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)]
        assert any("ingreso" in sql or "egreso" in sql for sql in constraints_sql), (
            f"Expected tipo check constraint with ingreso/egreso, got: {constraints_sql}"
        )
