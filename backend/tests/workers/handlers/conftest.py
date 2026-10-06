"""Reuse the throwaway-schema Postgres fixtures of the ML publications store tests."""

from tests.services.ml_publications.conftest import bridge_pg, mlpub_pg  # noqa: F401  (fixture re-exports)
