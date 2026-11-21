"""The T4 dry-run script's arguments: a malformed `--control` is a usage error (exit 2 and a message), not a
traceback, and it is refused before any database URL is read."""

from __future__ import annotations

import pytest

from app.scripts import costo_si_t4_dry_run as script


def test_a_malformed_control_is_a_usage_error(tmp_path, capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(script.URL_ENV, "postgresql://usuario@localhost/ejemplo")

    with pytest.raises(SystemExit) as salida:
        script.main(["--out", str(tmp_path), "--control", "22-16.79"])

    assert salida.value.code == 2
    assert "--control expects ITEM=AVERAGE, got '22-16.79'" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
