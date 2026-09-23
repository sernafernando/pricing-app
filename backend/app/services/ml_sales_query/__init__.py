"""Shared ML sales query layer (design D12).

One filter/scope builder (`filters.build_scope`) used by the listing
endpoint, free-text search (`search.py`) and, in a later PR, the KPI
aggregation endpoint -- so listing and KPI can never diverge on what a
"sale" matching a given filter combination means.
"""
