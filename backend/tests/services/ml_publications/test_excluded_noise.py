"""Excluded-noise policy (spec "Volatile and excluded field policy")."""

from __future__ import annotations

import pytest

from app.services.ml_publications import diff as diff_module
from app.services.ml_publications.diff import Change, assert_justified, split_excluded


def _changes():
    return [
        Change("status", "replace", "paused", "active"),
        Change("thumbnail", "replace", "a", "b"),
        Change("pictures[1].url", "replace", "u1", "u2"),
    ]


def test_shipped_constant_is_empty_and_valid():
    assert diff_module.EXCLUDED_NOISE == {}
    assert_justified(diff_module.EXCLUDED_NOISE)


def test_empty_list_reports_every_field_difference():
    reportable, excluded = split_excluded(_changes(), "item")
    assert reportable == _changes()
    assert excluded == []


def test_excluded_only_diff_has_no_reportable_changes(monkeypatch):
    monkeypatch.setattr(
        diff_module, "EXCLUDED_NOISE", {("item", "thumbnail"): "ML rewrites the thumbnail URL on every fetch"}
    )
    only = [Change("thumbnail", "replace", "a", "b")]
    reportable, excluded = split_excluded(only, "item")
    assert reportable == [] and excluded == only


def test_mixed_diff_lists_only_non_excluded_paths(monkeypatch):
    monkeypatch.setattr(
        diff_module,
        "EXCLUDED_NOISE",
        {("item", "thumbnail"): "justified", ("item", "pictures[*].url"): "justified too"},
    )
    reportable, excluded = split_excluded(_changes(), "item")
    assert [c.path for c in reportable] == ["status"]
    assert [c.path for c in excluded] == ["thumbnail", "pictures[1].url"]


def test_exclusion_is_scoped_to_its_resource_type(monkeypatch):
    monkeypatch.setattr(diff_module, "EXCLUDED_NOISE", {("prices", "thumbnail"): "justified"})
    reportable, excluded = split_excluded(_changes(), "item")
    assert excluded == [] and len(reportable) == 3


def test_descendants_of_an_excluded_path_are_excluded(monkeypatch):
    monkeypatch.setattr(diff_module, "EXCLUDED_NOISE", {("item", "shipping"): "justified"})
    changes = [Change("shipping.logistic_type", "replace", "a", "b")]
    assert split_excluded(changes, "item") == ([], changes)


@pytest.mark.parametrize("justification", ["", "   "])
def test_entry_without_justification_is_rejected(monkeypatch, justification):
    monkeypatch.setattr(diff_module, "EXCLUDED_NOISE", {("item", "thumbnail"): justification})
    with pytest.raises(ValueError, match="justification"):
        assert_justified(diff_module.EXCLUDED_NOISE)
    with pytest.raises(ValueError, match="justification"):
        split_excluded(_changes(), "item")
