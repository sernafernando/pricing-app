"""Memory limits for the pricing services: `deploy/systemd/<unit>.service.d/memory.conf`, and how
`deploy.sh` installs them.

The limits are a safety net, not the fix (that is finding which requests make pricing-api keep its
memory). A limit that kills the API under normal load is worse than none, so each one is pinned
above the real peaks measured on prod, with margin, and all of them together must still fit the CT.
"""

from __future__ import annotations

import configparser
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.deploy.test_deploy_workers import Env

REPO = Path(__file__).resolve().parents[3]
SYSTEMD = REPO / "deploy" / "systemd"
UNITS = ("pricing-api", "pricing-worker", "pricing-worker-ml")

GIB = 1024**3
# Highest peaks systemd logged on prod (journal "memory peak" on stop, and cgroup memory.peak),
# 18/11-24/11. pricing-api reached 6.5G after 76 h of uptime; worker-ml plateaus at 2.4-2.7G.
MEASURED_PEAK = {"pricing-api": 6.5 * GIB, "pricing-worker": 0.35 * GIB, "pricing-worker-ml": 2.7 * GIB}
# The apps CT is 16 GB; the other services there (journald, ml-webhook, gbs, nginx...) peaked at about 2.4G.
CT_LIMIT = 16 * GIB
OTHERS_PEAK = 2.4 * GIB


def dropin(unit: str) -> Path:
    return SYSTEMD / f"{unit}.service.d" / "memory.conf"


def service(unit: str) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read(dropin(unit), encoding="utf-8")
    return parser["Service"]


def size(value: str) -> float:
    units = {"K": 1024, "M": 1024**2, "G": GIB}
    return float(value[:-1]) * units[value[-1]] if value[-1] in units else float(value)


class TestTheLimits:
    @pytest.mark.parametrize("unit", UNITS)
    def test_every_service_gets_malloc_arena_max_2_and_restart_always(self, unit) -> None:
        assert "MALLOC_ARENA_MAX=2" in service(unit)["Environment"].split()
        assert service(unit)["Restart"] == "always"

    def test_only_the_api_gets_a_fixed_mmap_threshold(self) -> None:
        # pricing-api: multi-MB replies under concurrency kept +209 MB per worker with glibc's moving
        # threshold, +19 MB with a fixed 1M one (p95 and req/s unchanged on #2384's synthetic load).
        # The workers have no measured gain, so they keep glibc's default.
        envs = {unit: service(unit)["Environment"].split() for unit in UNITS}

        assert envs == {
            "pricing-api": ["MALLOC_ARENA_MAX=2", "MALLOC_MMAP_THRESHOLD_=1048576"],
            "pricing-worker": ["MALLOC_ARENA_MAX=2"],
            "pricing-worker-ml": ["MALLOC_ARENA_MAX=2"],
        }

    @pytest.mark.parametrize("unit", ["pricing-worker", "pricing-worker-ml"])
    def test_a_worker_soft_limit_is_well_above_its_real_peak_and_below_the_hard_one(self, unit) -> None:
        high, hard = size(service(unit)["MemoryHigh"]), size(service(unit)["MemoryMax"])
        # MemoryHigh throttles (no swap here, so it stalls allocations): never near a real peak.
        assert high >= MEASURED_PEAK[unit] * 1.25, f"{unit}: MemoryHigh too close to the measured peak"
        assert hard > high

    def test_the_api_is_never_throttled_and_its_kill_limit_is_well_above_the_real_peak(self) -> None:
        # MemoryHigh would throttle all four workers at once and, with no swap, could keep the whole API
        # slow for hours without killing anything: losing one worker at MemoryMax is the better failure.
        assert "MemoryHigh" not in service("pricing-api")
        assert size(service("pricing-api")["MemoryMax"]) >= MEASURED_PEAK["pricing-api"] + 1.5 * GIB

    def test_together_the_hard_limits_leave_room_for_the_rest_of_the_ct(self) -> None:
        total = sum(size(service(unit)["MemoryMax"]) for unit in UNITS)
        assert total + OTHERS_PEAK <= CT_LIMIT

    def test_an_oom_kill_in_the_api_takes_one_worker_not_the_whole_service(self) -> None:
        # uvicorn's supervisor replaces a dead worker (checked with uvicorn 0.50.2 + kill -9); with the
        # default OOMPolicy=stop systemd would stop and restart all four workers instead.
        assert service("pricing-api")["OOMPolicy"] == "continue"


class Deploy(Env):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        shutil.copytree(SYSTEMD, self.project / "deploy" / "systemd")
        self.etc = root / "etc-systemd"
        for unit in UNITS:
            self.mark("installed", unit)

    def go(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return self.run(
            Path(REPO / "deploy.sh"),
            "--skip-pull",
            "--skip-build",
            *args,
            extra_env={"SYSTEMD_DIR": str(self.etc), **env},
        )

    def installed(self) -> dict[str, str]:
        return {str(p.relative_to(self.etc)): p.read_text() for p in sorted(self.etc.rglob("*.conf"))}

    def reloads(self) -> int:
        return self.calls().count("systemctl daemon-reload")


@pytest.fixture()
def deploy(tmp_path) -> Deploy:
    return Deploy(tmp_path)


def output(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


class TestTheDeployInstallsThem:
    def test_the_dropins_are_installed_and_systemd_reloaded_before_the_api_restart(self, deploy) -> None:
        result = deploy.go()

        assert result.returncode == 0, output(result)
        assert deploy.installed() == {f"{unit}.service.d/memory.conf": dropin(unit).read_text() for unit in UNITS}
        calls = deploy.calls()
        assert calls.index("systemctl daemon-reload") < calls.index("systemctl restart pricing-api")

    def test_an_unchanged_dropin_is_not_copied_again_nor_reloaded(self, deploy) -> None:
        deploy.go()
        before = deploy.reloads()

        result = deploy.go()

        assert result.returncode == 0, output(result)
        assert deploy.reloads() == before
        assert "instalado" not in result.stdout

    def test_a_changed_dropin_is_reinstalled(self, deploy) -> None:
        deploy.go()
        live = deploy.etc / "pricing-api.service.d" / "memory.conf"
        live.write_text("[Service]\nMemoryMax=1G\n")

        reloads = deploy.reloads()

        result = deploy.go()

        assert result.returncode == 0, output(result)
        assert live.read_text() == dropin("pricing-api").read_text()
        assert f"instalado {live}" in result.stdout
        assert deploy.reloads() == reloads + 1

    def test_the_installed_dropins_are_readable_root_files_not_executable(self, deploy) -> None:
        deploy.go()

        modes = {p.name: p.stat().st_mode & 0o777 for p in deploy.etc.rglob("*.conf")}
        assert set(modes.values()) == {0o644}

    def test_a_failed_daemon_reload_only_warns_and_the_deploy_finishes(self, deploy) -> None:
        real = deploy.stub / "bin" / "systemctl"
        real.rename(deploy.stub / "systemctl.real")
        deploy._write(
            real,
            '#!/usr/bin/env bash\n[ "$1" = daemon-reload ] && { echo "systemctl $*" >> "$STUB_DIR/calls.log"; exit 1; }\n'
            'exec "$STUB_DIR/systemctl.real" "$@"\n',
        )

        result = deploy.go()

        assert result.returncode == 0, output(result)
        assert "Falló systemctl daemon-reload" in result.stdout
        assert deploy.notifications()[-1].startswith("Pricing App - deploy terminado")

    def test_a_unit_missing_on_this_server_only_warns_and_gets_nothing(self, deploy) -> None:
        (deploy.stub / "state" / "installed" / "pricing-worker-ml").unlink()

        result = deploy.go()

        assert result.returncode == 0, output(result)
        assert "pricing-worker-ml.service.d/memory.conf" not in deploy.installed()
        assert "No existe pricing-worker-ml en este server" in result.stdout

    def test_a_failed_install_only_warns_and_the_deploy_finishes(self, deploy) -> None:
        deploy.etc.write_text("not a directory")  # install -D cannot create anything under it

        result = deploy.go()

        assert result.returncode == 0, output(result)
        assert "No se pudo instalar" in result.stdout
        assert deploy.reloads() == 0
        assert deploy.notifications()[-1].startswith("Pricing App - deploy terminado")

    def test_skip_backend_leaves_the_dropins_alone(self, deploy) -> None:
        result = deploy.go("--skip-backend")

        assert result.returncode == 0, output(result)
        assert not deploy.etc.exists()
        assert deploy.reloads() == 0
