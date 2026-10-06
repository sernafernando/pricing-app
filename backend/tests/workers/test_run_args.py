"""`app.workers.run` arguments (design D1): the bare command line keeps its meaning; the ML
worker is selected explicitly with `--registry ml_publications --worker-name worker-ml`."""

from __future__ import annotations

import pytest

from app.workers import registry, run


class FakeRuntime:
    instances: list["FakeRuntime"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.listener_mode = "poll_only"
        FakeRuntime.instances.append(self)

    def run_forever(self) -> None:
        return None

    def stop(self) -> None:
        return None


@pytest.fixture()
def fake_runtime(monkeypatch):
    FakeRuntime.instances = []
    monkeypatch.setattr(run, "WorkerRuntime", FakeRuntime)
    monkeypatch.setattr(run.signal, "signal", lambda *args, **kwargs: None)
    return FakeRuntime


class TestDefaults:
    def test_no_arguments_keeps_todays_registry_and_worker_name(self, fake_runtime) -> None:
        run.main([])

        kwargs = fake_runtime.instances[0].kwargs
        assert kwargs["worker_name"] == "worker"
        assert kwargs.get("registry") is None  # the runtime then uses REGISTRY, exactly as before

    def test_the_default_registry_can_be_named_explicitly(self, fake_runtime) -> None:
        run.main(["--registry", "default"])

        kwargs = fake_runtime.instances[0].kwargs
        assert kwargs["worker_name"] == "worker" and kwargs.get("registry") is None


class TestMlPublications:
    def test_selects_the_ml_registry_and_worker_name(self, fake_runtime) -> None:
        run.main(["--registry", "ml_publications", "--worker-name", "worker-ml"])

        kwargs = fake_runtime.instances[0].kwargs
        assert kwargs["worker_name"] == "worker-ml"
        assert kwargs["registry"] is registry.ML_PUBLICATIONS_REGISTRY

    def test_the_ml_registry_never_runs_under_the_default_worker_name(self, fake_runtime) -> None:
        """Both processes write a heartbeat row keyed by worker name: sharing `worker` would
        make the two processes mask each other's death."""
        run.main(["--registry", "ml_publications"])

        assert fake_runtime.instances[0].kwargs["worker_name"] == "worker-ml"

    def test_an_unknown_registry_exits_non_zero_without_starting_anything(self, fake_runtime) -> None:
        with pytest.raises(SystemExit) as exit_info:
            run.main(["--registry", "nope"])

        assert exit_info.value.code != 0
        assert fake_runtime.instances == []

    def test_a_blank_worker_name_is_rejected(self, fake_runtime) -> None:
        with pytest.raises(SystemExit) as exit_info:
            run.main(["--registry", "ml_publications", "--worker-name", " "])

        assert exit_info.value.code != 0
