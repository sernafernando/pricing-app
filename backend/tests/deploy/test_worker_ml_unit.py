"""`deploy/systemd/pricing-worker-ml.service` (design D1): the second worker process.

Static checks over the unit file, with the existing `pricing-worker.service` as the reference
for everything that must not drift (user, paths, restart policy).
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

SYSTEMD = Path(__file__).resolve().parents[3] / "deploy" / "systemd"
ML_UNIT = SYSTEMD / "pricing-worker-ml.service"
BASE_UNIT = SYSTEMD / "pricing-worker.service"

EXPECTED_EXEC = (
    "/var/www/html/pricing-app/backend/venv/bin/python -m app.workers.run "
    "--registry ml_publications --worker-name worker-ml"
)


def read_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read(path, encoding="utf-8")
    return parser


@pytest.fixture(scope="module")
def ml_unit() -> configparser.ConfigParser:
    return read_unit(ML_UNIT)


@pytest.fixture(scope="module")
def base_unit() -> configparser.ConfigParser:
    return read_unit(BASE_UNIT)


class TestExecStart:
    def test_exec_start_is_the_fixed_command_line(self, ml_unit) -> None:
        assert ml_unit["Service"]["ExecStart"] == EXPECTED_EXEC

    def test_exec_start_is_composed_from_nothing_at_runtime(self) -> None:
        text = ML_UNIT.read_text(encoding="utf-8")
        assert "$" not in text.split("ExecStart=", 1)[1].splitlines()[0]
        assert "%" not in text.split("ExecStart=", 1)[1].splitlines()[0]
        assert "ExecStartPre" not in text and "ExecStartPost" not in text


class TestMirrorsTheBaseWorker:
    @pytest.mark.parametrize(
        "key", ["Type", "User", "Group", "WorkingDirectory", "EnvironmentFile", "Environment", "Restart", "RestartSec"]
    )
    def test_service_key_matches_pricing_worker(self, ml_unit, base_unit, key) -> None:
        assert ml_unit["Service"][key] == base_unit["Service"][key]

    def test_restart_policy_is_always_so_a_dead_heartbeat_exit_is_picked_up(self, ml_unit) -> None:
        assert ml_unit["Service"]["Restart"] == "always"

    def test_it_starts_after_the_same_dependencies(self, ml_unit, base_unit) -> None:
        for key in ("After", "Wants"):
            assert ml_unit["Unit"][key] == base_unit["Unit"][key]

    def test_install_target_matches(self, ml_unit, base_unit) -> None:
        assert ml_unit["Install"]["WantedBy"] == base_unit["Install"]["WantedBy"]


class TestNoSchedulingMachinery:
    def test_the_unit_has_no_timer_section_or_calendar(self, ml_unit) -> None:
        assert set(ml_unit.sections()) == {"Unit", "Service", "Install"}
        assert "OnCalendar" not in ML_UNIT.read_text(encoding="utf-8")

    def test_no_timer_file_is_shipped_for_the_ml_worker(self) -> None:
        assert [p.name for p in SYSTEMD.glob("*.timer") if "worker" in p.name] == []
