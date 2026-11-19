"""The pre-deploy backup only dumps the allocation tables (`app.scripts.backup_tabla_csv`)."""

import pytest

from app.scripts.backup_tabla_csv import copy_sql, main


def test_an_allocation_table_is_copied_read_only_by_id() -> None:
    assert (
        copy_sql("sell_out_consumos") == "COPY (SELECT * FROM sell_out_consumos ORDER BY id) TO STDOUT WITH CSV HEADER"
    )


@pytest.mark.parametrize("tabla", ["usuarios", "sell_out_consumos; DROP TABLE x"])
def test_any_other_table_is_refused_without_touching_the_database(tabla: str, capsys) -> None:
    assert main([tabla]) == 2
    assert "tabla no permitida" in capsys.readouterr().err


def test_without_exactly_one_table_it_prints_the_usage(capsys) -> None:
    assert main([]) == 2
    assert "uso:" in capsys.readouterr().err
