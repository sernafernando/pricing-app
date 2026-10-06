"""Deploy step 6b (`scripts/restart-verify-workers.sh`, called from `deploy.sh`): both workers
are restarted and then VERIFIED, not just restarted.

The bash is exercised for real. `sudo`, `systemctl`, `curl`, the heartbeat probe and the WhatsApp
notifier are stubs on PATH whose behavior is driven by marker files, so each scenario (missing
unit, restart failure, dead worker, hung worker whose heartbeat stopped) is a few `touch`es.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
VERIFY_SCRIPT = REPO / "scripts" / "restart-verify-workers.sh"
DEPLOY_SCRIPT = REPO / "deploy.sh"

UNITS = {"worker": "pricing-worker", "worker-ml": "pricing-worker-ml"}

SUDO_STUB = """#!/usr/bin/env bash
echo "sudo $*" >> "$STUB_DIR/calls.log"
exec "$@"
"""

SYSTEMCTL_STUB = """#!/usr/bin/env bash
echo "systemctl $*" >> "$STUB_DIR/calls.log"
S="$STUB_DIR/state"
cmd=$1; shift
quiet=false
[ "${1:-}" = "--quiet" ] && { quiet=true; shift; }
unit=${1:-}
case "$cmd" in
  cat) [ -e "$S/installed/$unit" ] ;;
  is-enabled) [ -e "$S/enabled/$unit" ] ;;
  is-active) [ -e "$S/active/$unit" ] ;;
  restart)
    [ -e "$S/restart_fails/$unit" ] && exit 1
    touch "$S/restarted/$unit"
    # the OLD process writes one last heartbeat while it shuts down
    if [ -e "$S/late_old_beat/$unit" ]; then
      case "$unit" in pricing-worker) n=worker ;; *) n=worker-ml ;; esac
      echo 2000 > "$S/hb/$n"
    fi
    if [ -e "$S/no_start/$unit" ]; then rm -f "$S/active/$unit"; else touch "$S/active/$unit"; fi
    ;;
  *) exit 0 ;;
esac
"""

PROBE_STUB = """#!/usr/bin/env bash
S="$STUB_DIR/state"
name=$1
case "$name" in worker) unit=pricing-worker ;; worker-ml) unit=pricing-worker-ml ;; *) unit=$name ;; esac
[ -e "$S/probe_fails" ] && exit 1
if [ -e "$S/restarted/$unit" ] && [ ! -e "$S/hung/$unit" ]; then
  n=$(cat "$S/ticks/$unit" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$S/ticks/$unit"
  echo $((5000 + n)); exit 0   # a live worker's heartbeat advances on every read
fi
if [ -e "$S/hb/$name" ]; then cat "$S/hb/$name"; else echo none; fi
"""

CURL_STUB = """#!/usr/bin/env bash
[ -e "$STUB_DIR/state/backend_down" ] && exit 22
exit 0
"""

NOTIFY_STUB = """#!/usr/bin/env bash
printf '%s\\n----\\n' "$1" >> "$STUB_DIR/notify.log"
"""


class Env:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.stub = root / "stub"
        self.project = root / "project"
        for sub in (
            "installed",
            "enabled",
            "active",
            "restart_fails",
            "no_start",
            "hung",
            "restarted",
            "hb",
            "ticks",
            "late_old_beat",
        ):
            (self.stub / "state" / sub).mkdir(parents=True)
        bin_dir = self.stub / "bin"
        bin_dir.mkdir()
        for name, body in (("sudo", SUDO_STUB), ("systemctl", SYSTEMCTL_STUB), ("curl", CURL_STUB)):
            self._write(bin_dir / name, body)
        self._write(self.stub / "probe", PROBE_STUB)
        (self.project / "scripts").mkdir(parents=True)
        (self.project / "backend").mkdir()
        if VERIFY_SCRIPT.exists():
            shutil.copy(VERIFY_SCRIPT, self.project / "scripts" / VERIFY_SCRIPT.name)
        self._write(self.project / "scripts" / "notify-wabot.sh", NOTIFY_STUB)

    @staticmethod
    def _write(path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    # --- scenario setup -------------------------------------------------------------
    def mark(self, kind: str, unit: str) -> None:
        (self.stub / "state" / kind / unit).touch()

    def healthy(self, unit: str, heartbeat: str = "1000", *, active: bool = True) -> None:
        name = next(n for n, u in UNITS.items() if u == unit)
        self.mark("installed", unit)
        self.mark("enabled", unit)
        if active:
            self.mark("active", unit)
        (self.stub / "state" / "hb" / name).write_text(heartbeat)

    def flag(self, name: str) -> None:
        (self.stub / "state" / name).touch()

    # --- observation ------------------------------------------------------------------
    def calls(self) -> list[str]:
        log = self.stub / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def restarted(self) -> list[str]:
        return [c.split()[-1] for c in self.calls() if c.startswith("systemctl restart ")]

    def notifications(self) -> list[str]:
        log = self.stub / "notify.log"
        return [m.strip() for m in log.read_text().split("----\n") if m.strip()] if log.exists() else []

    def run(self, script: Path, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{self.stub / 'bin'}:/usr/bin:/bin",
            "STUB_DIR": str(self.stub),
            "WORKER_HEARTBEAT_PROBE": str(self.stub / "probe"),
            "WORKER_VERIFY_TIMEOUT": "2",
            "WORKER_VERIFY_POLL": "0.1",
            "PROJECT_DIR": str(self.project),
            "HEALTHCHECK_TIMEOUT": "1",
            "HOME": str(self.root),
            **(extra_env or {}),
        }
        return subprocess.run(
            ["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=60, cwd=self.project
        )

    def verify(self) -> subprocess.CompletedProcess:
        return self.run(self.project / "scripts" / VERIFY_SCRIPT.name)

    def deploy(self, *args: str) -> subprocess.CompletedProcess:
        return self.run(DEPLOY_SCRIPT, "--skip-pull", "--skip-build", *args)


@pytest.fixture()
def env(tmp_path) -> Env:
    return Env(tmp_path)


def problems(result: subprocess.CompletedProcess) -> list[str]:
    return [line for line in result.stdout.splitlines() if line.startswith("PROBLEM ")]


class TestBothWorkersAreRestartedAndVerified:
    def test_two_healthy_workers_are_restarted_checked_and_reported(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")

        result = env.verify()

        assert result.returncode == 0 and problems(result) == []
        assert sorted(env.restarted()) == ["pricing-worker", "pricing-worker-ml"]
        assert "systemctl is-active --quiet pricing-worker" in env.calls()
        assert "systemctl is-active --quiet pricing-worker-ml" in env.calls()
        # the deploy output names each worker's state
        assert "pricing-worker:" in result.stderr and "pricing-worker-ml:" in result.stderr

    def test_the_existing_worker_is_verified_not_only_restarted(self, env) -> None:
        env.healthy("pricing-worker")
        env.flag("probe_fails")  # nothing can be read

        result = env.verify()

        assert any("pricing-worker" in line and "heartbeat" in line for line in problems(result))

    def test_a_worker_that_never_wrote_a_heartbeat_is_fine_once_it_writes_one(self, env) -> None:
        env.mark("installed", "pricing-worker")
        env.mark("active", "pricing-worker")  # no baseline heartbeat row at all

        result = env.verify()

        assert result.returncode == 0 and problems(result) == []


class TestTheMlWorkerIsOptional:
    def test_a_missing_ml_unit_only_warns(self, env) -> None:
        env.healthy("pricing-worker")

        result = env.verify()

        assert result.returncode == 0 and problems(result) == []
        assert env.restarted() == ["pricing-worker"]
        assert "pricing-worker-ml" in result.stderr and "WARN" in result.stderr

    def test_an_installed_but_not_enabled_unit_is_not_started_by_the_deploy(self, env) -> None:
        env.healthy("pricing-worker")
        env.mark("installed", "pricing-worker-ml")  # neither enabled nor active

        result = env.verify()

        assert result.returncode == 0 and problems(result) == []
        assert env.restarted() == ["pricing-worker"]
        assert "no habilitado" in result.stderr

    def test_an_enabled_unit_that_is_currently_stopped_is_restarted(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml", active=False)

        result = env.verify()

        assert result.returncode == 0 and problems(result) == []
        assert sorted(env.restarted()) == ["pricing-worker", "pricing-worker-ml"]


class TestFailuresAreNamedAndNeverAbort:
    def test_a_missing_main_worker_unit_is_a_problem(self, env) -> None:
        env.healthy("pricing-worker-ml")

        result = env.verify()

        assert [p for p in problems(result) if p.startswith("PROBLEM pricing-worker:")]
        assert "pricing-worker-ml" in env.restarted()

    def test_a_failed_restart_names_the_worker_and_the_other_one_is_still_handled(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")
        env.mark("restart_fails", "pricing-worker")

        result = env.verify()

        assert result.returncode == 1
        assert [p for p in problems(result) if p.startswith("PROBLEM pricing-worker:") and "reiniciar" in p]
        assert not [p for p in problems(result) if p.startswith("PROBLEM pricing-worker-ml")]
        assert "pricing-worker-ml" in env.restarted()

    def test_a_worker_that_is_not_active_after_the_restart_is_reported(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")
        env.mark("no_start", "pricing-worker-ml")

        result = env.verify()

        (line,) = problems(result)
        assert line.startswith("PROBLEM pricing-worker-ml:") and "activo" in line

    def test_a_hung_worker_alive_but_with_a_stale_heartbeat_is_reported(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")
        env.mark("hung", "pricing-worker")

        result = env.verify()

        (line,) = problems(result)
        assert line.startswith("PROBLEM pricing-worker:") and "heartbeat" in line and "colgado" in line

    def test_the_last_heartbeat_of_the_old_process_does_not_vouch_for_the_new_one(self, env) -> None:
        """The old process writes one more heartbeat while shutting down, newer than anything read
        before the restart. A new process that never starts working must still be reported."""
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")
        env.mark("hung", "pricing-worker-ml")
        env.mark("late_old_beat", "pricing-worker-ml")

        (line,) = problems(env.verify())

        assert line.startswith("PROBLEM pricing-worker-ml:") and "colgado" in line

    def test_both_workers_failing_are_both_named(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")
        env.mark("hung", "pricing-worker")
        env.mark("no_start", "pricing-worker-ml")

        names = {p.split(":")[0] for p in problems(env.verify())}

        assert names == {"PROBLEM pricing-worker", "PROBLEM pricing-worker-ml"}

    def test_the_verification_never_exits_with_anything_but_zero_or_one(self, env) -> None:
        # Nothing installed at all, nothing readable: the worst case still ends in a clean exit.
        env.flag("probe_fails")

        assert env.verify().returncode in (0, 1)


class TestDeployIntegration:
    def healthy_both(self, env) -> None:
        env.healthy("pricing-worker")
        env.healthy("pricing-worker-ml")

    def test_a_clean_deploy_announces_success_and_verifies_both_workers(self, env) -> None:
        self.healthy_both(env)

        result = env.deploy()

        assert result.returncode == 0, result.stderr
        final = env.notifications()[-1]
        assert "CON PROBLEMAS" not in final and "deploy terminado" in final
        assert sorted(env.restarted()) == ["pricing-api", "pricing-worker", "pricing-worker-ml"]

    def test_a_hung_ml_worker_marks_the_final_announcement_but_never_aborts_the_deploy(self, env) -> None:
        self.healthy_both(env)
        env.mark("hung", "pricing-worker-ml")

        result = env.deploy()

        assert result.returncode == 0
        assert "Deploy completado" in result.stdout
        final = env.notifications()[-1]
        assert "CON PROBLEMAS" in final and "pricing-worker-ml" in final
        assert "deploy falló" not in final.lower()

    def test_a_hung_main_worker_is_named_too(self, env) -> None:
        self.healthy_both(env)
        env.mark("hung", "pricing-worker")

        env.deploy()

        final = env.notifications()[-1]
        assert "CON PROBLEMAS" in final and "pricing-worker:" in final
        assert "pricing-worker-ml:" not in final

    def test_a_missing_ml_unit_does_not_taint_the_announcement(self, env) -> None:
        env.healthy("pricing-worker")

        result = env.deploy()

        assert result.returncode == 0
        assert "CON PROBLEMAS" not in env.notifications()[-1]

    def test_a_backend_that_does_not_answer_still_reports_the_backend(self, env) -> None:
        self.healthy_both(env)
        env.flag("backend_down")

        result = env.deploy()

        assert result.returncode == 0
        final = env.notifications()[-1]
        assert "CON PROBLEMAS" in final and "pricing-api" in final

    def test_skip_backend_leaves_the_workers_alone(self, env) -> None:
        self.healthy_both(env)

        result = env.deploy("--skip-backend")

        assert result.returncode == 0
        assert env.restarted() == []
        assert "CON PROBLEMAS" not in env.notifications()[-1]

    def test_the_deploy_never_enables_the_ml_unit(self, env) -> None:
        self.healthy_both(env)

        env.deploy()

        assert not [c for c in env.calls() if " enable" in c or " start " in c]
