"""Reuse the throwaway-schema Postgres fixture of the ML publications store tests."""

from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401  (fixture re-export)
