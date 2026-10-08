"""P5.T5: `pubml.view` timing lines and the `Server-Timing` header (measure-first mechanism, design §4.6)."""

from __future__ import annotations

import logging

from app.services.ml_publications.view.timing import Timer


def test_stages_are_measured_and_reported_in_order() -> None:
    ticks = iter([0.0, 0.0, 0.010, 0.010, 0.035])  # start, then enter/exit of each stage
    timer = Timer("items", clock=lambda: next(ticks))
    with timer.stage("count"):
        pass
    with timer.stage("page"):
        pass
    assert timer.stages == {"count": 10.0, "page": 25.0}
    assert timer.server_timing() == "count;dur=10.0, page;dur=25.0"


def test_a_stage_that_raises_is_still_recorded() -> None:
    ticks = iter([0.0, 0.0, 0.007])
    timer = Timer("items", clock=lambda: next(ticks))
    try:
        with timer.stage("page"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert timer.stages == {"page": 7.0}


def test_the_log_line_names_the_endpoint_total_stages_and_extra_fields(caplog) -> None:
    ticks = iter([0.0, 0.001, 0.021, 0.050])  # start, stage start, stage end, emit
    timer = Timer("items", clock=lambda: next(ticks))
    with timer.stage("page"):
        pass
    with caplog.at_level(logging.INFO, logger="pubml.view"):
        line = timer.emit(rows=50, total=24600)
    assert line == "pubml.view endpoint=items total_ms=50.0 page_ms=20.0 rows=50 total=24600"
    assert [r.getMessage() for r in caplog.records] == [line]
