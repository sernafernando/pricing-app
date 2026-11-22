"""Deploy step 4 (`deploy.sh`): the frontend is built into `dist.new` and swapped into `dist` only when the build
succeeds, under a Node heap sized to the free memory, after a memory check that cancels the deploy before anything
is touched.

Incident 2026-11-22: the OOM killer killed `vite build` twice (exit 137) and, because vite empties its outDir when it
starts and the outDir was the published `dist`, the site was down for an hour.

The bash runs for real. `pnpm` is a stub on PATH that behaves like vite (empties the outDir it is given, then writes
or dies), `/proc/meminfo` is a fake file, and marker files pick each scenario.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.deploy.test_deploy_workers import Env

PNPM_STUB = """#!/usr/bin/env bash
S="$STUB_DIR/state"
echo "pnpm $* | WORKERS=${BUILD_TERSER_WORKERS:-} | NODE_OPTIONS=${NODE_OPTIONS:-}" >> "$STUB_DIR/pnpm.log"
case "$1" in
  install)
    # the free memory drops while the dependencies install (another service grows)
    [ -e "$S/mem_drops" ] && printf 'MemTotal: 16000000 kB\\nMemAvailable: 512000 kB\\n' > "$MEMINFO_FILE"
    exit 0 ;;
  run)
    out=""
    while [ $# -gt 0 ]; do [ "$1" = "--outDir" ] && out=$2; shift; done
    [ -n "$out" ] || out=dist  # vite's default outDir: what deploy.sh used to build into
    # like vite: the outDir is emptied as soon as the build starts
    rm -rf "$out"; mkdir -p "$out/assets"
    echo partial > "$out/assets/chunk-half.js"
    if [ -e "$S/build_oom" ]; then echo "rendering chunks..."; kill -9 $$; fi
    [ -e "$S/build_no_index" ] && exit 0
    echo new > "$out/index.html"
    exit 0 ;;
esac
exit 0
"""

# A `mv` without `--exchange` (coreutils < 9.5): the swap falls back to two renames.
# A `mv` that swaps fine but cannot move the old build out of the way afterwards (e.g. a full disk).
FAILING_PREV_MV_STUB = """#!/usr/bin/env bash
dest="${@: -1}"
[ "${dest##*/}" = "dist.prev" ] && { echo "mv: cannot move to $dest" >&2; exit 1; }
exec /usr/bin/mv "$@"
"""

# No `--exchange`, and a Ctrl+C reaches the deploy right while dist is being moved to dist.prev: the moment in
# the two-rename swap when dist does not exist.
INTERRUPTED_MV_STUB = """#!/usr/bin/env bash
for a in "$@"; do [ "$a" = "--exchange" ] && exit 1; done
dest="${@: -1}"
[ "${dest##*/}" = "dist.prev" ] && kill -INT "$PPID"
exec /usr/bin/mv "$@"
"""

OLD_MV_STUB = """#!/usr/bin/env bash
for a in "$@"; do [ "$a" = "--exchange" ] && { echo "mv: unrecognized option '--exchange'" >&2; exit 1; }; done
exec /usr/bin/mv "$@"
"""


class Build(Env):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._write(self.stub / "bin" / "pnpm", PNPM_STUB)
        self.frontend = self.project / "frontend"
        self.dist = self.frontend / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("old")
        (self.dist / "assets" / "app-old.js").write_text("old")
        self.meminfo = root / "meminfo"
        self.memory(8000)

    def memory(self, available_mb: int) -> None:
        self.meminfo.write_text(f"MemTotal: 16000000 kB\nMemAvailable: {available_mb * 1024} kB\n")

    def pnpm_calls(self) -> list[str]:
        log = self.stub / "pnpm.log"
        return log.read_text().splitlines() if log.exists() else []

    def builds(self) -> list[str]:
        return [c for c in self.pnpm_calls() if c.startswith("pnpm run build")]

    def tree(self, path: Path) -> dict[str, str]:
        return {str(p.relative_to(path)): p.read_text().strip() for p in sorted(path.rglob("*")) if p.is_file()}

    def build_deploy(self, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
        return self.run(
            Path(__file__).resolve().parents[3] / "deploy.sh",
            "--skip-pull",
            "--skip-backend",
            *args,
            extra_env={
                "MEMINFO_FILE": str(self.meminfo),
                "BUILD_MIN_FREE_MB": "5000",
                "BUILD_MAX_HEAP_MB": "4096",
                "BUILD_MEM_RESERVE_MB": "1024",
                **(extra_env or {}),
            },
        )


OLD_DIST = {"index.html": "old", "assets/app-old.js": "old"}


def output(result: subprocess.CompletedProcess) -> str:
    """What the person running the deploy sees: log/warn/err print to stdout, the process report to stderr."""
    return result.stdout + result.stderr


@pytest.fixture()
def env(tmp_path) -> Build:
    return Build(tmp_path)


class TestAFailedBuildNeverTouchesTheLiveDist:
    def test_an_oom_killed_build_leaves_dist_exactly_as_it_was(self, env) -> None:
        env.flag("build_oom")

        result = env.build_deploy()

        assert result.returncode == 137
        assert env.tree(env.dist) == OLD_DIST
        assert "Deploy interrumpido en: build del frontend" in output(result)
        assert "dist no se tocó" in output(result)
        fallo = env.notifications()[-1]
        assert fallo.startswith("Pricing App - EL DEPLOY FALLÓ")
        assert "Se cortó en: build del frontend" in fallo
        assert "El frontend publicado no se tocó: la app sigue con la versión anterior." in fallo

    def test_the_build_goes_to_dist_new_never_to_dist(self, env) -> None:
        env.build_deploy()

        (build,) = env.builds()
        assert f"--outDir {env.frontend / 'dist.new'} --emptyOutDir" in build

    def test_a_build_that_exits_0_without_an_index_is_not_published(self, env) -> None:
        env.flag("build_no_index")

        result = env.build_deploy()

        assert result.returncode != 0
        assert env.tree(env.dist) == OLD_DIST
        assert "Se cortó en: publicación del build (dist.new -> dist)" in env.notifications()[-1]


class TestASuccessfulBuildIsSwappedIn:
    def test_dist_gets_the_new_build_and_the_old_one_stays_in_dist_prev(self, env) -> None:
        result = env.build_deploy()

        assert result.returncode == 0, result.stderr
        assert env.tree(env.dist) == {"index.html": "new", "assets/chunk-half.js": "partial"}
        assert env.tree(env.frontend / "dist.prev") == OLD_DIST
        assert not (env.frontend / "dist.new").exists()
        assert env.notifications()[-1].startswith("Pricing App - deploy terminado")

    def test_without_mv_exchange_the_two_rename_swap_gives_the_same_result(self, env) -> None:
        env._write(env.stub / "bin" / "mv", OLD_MV_STUB)

        result = env.build_deploy()

        assert result.returncode == 0, result.stderr
        assert env.tree(env.dist)["index.html"] == "new"
        assert env.tree(env.frontend / "dist.prev") == OLD_DIST
        assert not (env.frontend / "dist.new").exists()

    def test_a_failure_to_keep_the_old_build_after_the_swap_is_only_a_warning(self, env) -> None:
        """Verifier finding: after the exchange the new build is live; failing to move the old one to dist.prev must
        not report a failed deploy that "did not touch" the frontend."""
        env._write(env.stub / "bin" / "mv", FAILING_PREV_MV_STUB)

        result = env.build_deploy()

        assert result.returncode == 0, output(result)
        assert env.tree(env.dist)["index.html"] == "new"
        assert "El build nuevo ya está publicado, pero el anterior no se pudo guardar" in output(result)
        assert env.notifications()[-1].startswith("Pricing App - deploy terminado")

    def test_a_ctrl_c_between_the_two_renames_never_leaves_the_site_without_dist(self, env) -> None:
        """Verifier finding: on coreutils < 9.5 the swap is two renames; a signal between them used to run the trap
        and exit with dist missing. The signals are ignored for those two `mv` only."""
        env._write(env.stub / "bin" / "mv", INTERRUPTED_MV_STUB)

        result = env.build_deploy()

        assert env.dist.is_dir(), output(result)
        assert env.tree(env.dist)["index.html"] == "new"
        assert env.tree(env.frontend / "dist.prev") == OLD_DIST

    def test_a_first_deploy_without_dist_publishes_the_build(self, env) -> None:
        subprocess.run(["rm", "-rf", str(env.dist)], check=True)

        result = env.build_deploy()

        assert result.returncode == 0, result.stderr
        assert env.tree(env.dist)["index.html"] == "new"

    def test_a_second_deploy_replaces_the_previous_dist_prev(self, env) -> None:
        env.build_deploy()
        (env.dist / "index.html").write_text("second-live")

        env.build_deploy()

        assert env.tree(env.frontend / "dist.prev")["index.html"] == "second-live"


class TestTheNodeHeapFollowsTheFreeMemory:
    def test_the_heap_is_free_memory_minus_the_reserve(self, env) -> None:
        env.memory(5000)

        env.build_deploy()

        assert env.builds()[0].endswith("NODE_OPTIONS=--max-old-space-size=3976")

    def test_the_heap_is_capped(self, env) -> None:
        env.memory(12000)

        env.build_deploy()

        assert env.builds()[0].endswith("NODE_OPTIONS=--max-old-space-size=4096")

    def test_existing_node_options_are_kept(self, env) -> None:
        env.build_deploy(extra_env={"NODE_OPTIONS": "--enable-source-maps"})

        assert env.builds()[0].endswith("NODE_OPTIONS=--enable-source-maps --max-old-space-size=4096")

    def test_the_heap_flag_and_the_workers_reach_only_the_build(self, env) -> None:
        env.build_deploy()

        (install,) = [c for c in env.pnpm_calls() if c.startswith("pnpm install")]
        assert install.endswith("| WORKERS= | NODE_OPTIONS=")
        assert "| WORKERS=2 |" in env.builds()[0]

    def test_the_terser_workers_can_be_overridden(self, env) -> None:
        env.build_deploy(extra_env={"BUILD_TERSER_WORKERS": "1"})

        assert "| WORKERS=1 |" in env.builds()[0]

    def test_unreadable_meminfo_warns_and_builds_with_the_cap(self, env) -> None:
        result = env.build_deploy(extra_env={"MEMINFO_FILE": str(env.root / "missing")})

        assert result.returncode == 0, result.stderr
        assert "No se pudo leer la memoria disponible" in output(result)
        assert env.builds()[0].endswith("NODE_OPTIONS=--max-old-space-size=4096")


class TestLowMemoryFailsEarly:
    def test_low_memory_cancels_before_touching_anything(self, env) -> None:
        env.memory(2000)

        result = env.build_deploy()

        assert result.returncode == 1
        assert env.pnpm_calls() == []
        assert env.tree(env.dist) == OLD_DIST
        assert "hay 2000 MB disponibles y hacen falta 5000 MB" in output(result)
        assert "Lo que más memoria ocupa" in output(result)
        (aviso,) = env.notifications()  # no "arranca el deploy" before it
        assert aviso.startswith("Pricing App - deploy cancelado")
        assert "2000 MB disponibles, hacen falta 5000 MB" in aviso
        assert "No se tocó nada" in aviso

    def test_memory_that_drops_during_the_deploy_stops_it_before_the_build(self, env) -> None:
        env.flag("mem_drops")

        result = env.build_deploy()

        assert result.returncode != 0
        assert env.builds() == []
        assert env.tree(env.dist) == OLD_DIST
        assert "hay 500 MB disponibles y hacen falta 5000 MB" in output(result)
        fallo = env.notifications()[-1]
        assert "Se cortó en: chequeo de memoria para el build" in fallo
        assert "El frontend publicado no se tocó" in fallo

    def test_a_minimum_below_the_reserve_plus_the_smallest_heap_is_raised_to_it(self, env) -> None:
        """BUILD_MIN_FREE_MB=3000 with a 1024 MB reserve would give a 2476 MB heap, below the 3072 MB the build needs
        (a negative one Node silently ignores): the real floor, 1024 + 3072, is what is required and reported."""
        env.memory(3500)

        result = env.build_deploy(extra_env={"BUILD_MIN_FREE_MB": "3000"})

        assert result.returncode == 1
        assert env.pnpm_calls() == []
        assert "hay 3500 MB disponibles y hacen falta 4096 MB" in output(result)

    def test_skip_build_never_checks_memory(self, env) -> None:
        env.memory(100)

        result = env.build_deploy("--skip-build")

        assert result.returncode == 0, result.stderr
        assert env.pnpm_calls() == []
        assert env.notifications()[-1].startswith("Pricing App - deploy terminado")
