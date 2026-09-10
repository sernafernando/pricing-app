"""OC-match package. Phase 1: MIME classify + vendored GBP template only."""

from app.services.oc_match.mime import KIND_GEMINI, KIND_OFFICE, KIND_UNKNOWN, classify

__all__ = ["KIND_GEMINI", "KIND_OFFICE", "KIND_UNKNOWN", "classify"]
