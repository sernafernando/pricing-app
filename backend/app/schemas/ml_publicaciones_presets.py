"""Schemas of the Publicaciones ML column layouts and presets (`routers/ml_publications_presets.py`, S2-S4).

Every body forbids unknown fields. Keys (column keys and URL param names) match `^[a-z0-9_]{1,64}$`. A column
layout holds at most 200 entries in `visibility` and in `order`, `order` without duplicates. A preset's `params`
are the page's URL search params as strings (at most 80, values up to 2000 chars), never the navigation ones
(`vista`, `pagina`, `sel`, `tab`, `prod`); the backend stores them opaquely. A serialized payload over 32 KB is
refused. Every violation is a 422 before anything is written.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Vista = Literal["publicacion", "precios", "producto", "agrupado", "auditoria"]

Key = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]
ParamValue = Annotated[str, StringConstraints(max_length=2000)]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]

MAX_COLUMN_ENTRIES = 200
MAX_PARAMS = 80
MAX_PAYLOAD_BYTES = 32 * 1024
# URL params that only navigate inside the page (view, page, selection, panel tab, opened product): never saved.
NAVIGATION_PARAMS = frozenset({"vista", "pagina", "sel", "tab", "prod"})


def _serialized_size(value: dict) -> int:
    """Bytes of `value` serialized compactly as UTF-8 JSON, the size the cap measures."""
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


class ColumnLayout(BaseModel):
    """Which columns are shown and in what order (keys the frontend's column ids)."""

    model_config = ConfigDict(extra="forbid")

    visibility: dict[Key, bool] = Field(max_length=MAX_COLUMN_ENTRIES)
    order: list[Key] = Field(max_length=MAX_COLUMN_ENTRIES)

    @field_validator("order")
    @classmethod
    def _order_without_duplicates(cls, order: list[str]) -> list[str]:
        if len(set(order)) != len(order):
            raise ValueError("order must not repeat a column")
        return order

    @model_validator(mode="after")
    def _size_cap(self) -> "ColumnLayout":
        if _serialized_size(self.model_dump()) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"columns over {MAX_PAYLOAD_BYTES} bytes")
        return self


class PresetPayload(BaseModel):
    """What a preset applies at once: the column layout and the page's URL params (filters, sort, mode...)."""

    model_config = ConfigDict(extra="forbid")

    columns: ColumnLayout
    params: dict[Key, ParamValue] = Field(max_length=MAX_PARAMS)

    @field_validator("params")
    @classmethod
    def _no_navigation_params(cls, params: dict[str, str]) -> dict[str, str]:
        navigation = sorted(NAVIGATION_PARAMS.intersection(params))
        if navigation:
            raise ValueError(f"params must not include navigation keys: {navigation}")
        return params

    @model_validator(mode="after")
    def _size_cap(self) -> "PresetPayload":
        if _serialized_size(self.model_dump()) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload over {MAX_PAYLOAD_BYTES} bytes")
        return self


class LayoutBody(BaseModel):
    """A user's layout of one view: `{columns: null, preset_activo_id: null}` is "Restablecer"."""

    model_config = ConfigDict(extra="forbid")

    columns: Optional[ColumnLayout] = None
    preset_activo_id: Optional[int] = None


class PresetCreate(BaseModel):
    """A new preset; `compartido` makes it shared (needs `ml_publicaciones.presets_compartidos`)."""

    model_config = ConfigDict(extra="forbid")

    vista: Vista
    nombre: Nombre
    compartido: bool = False
    payload: PresetPayload


class PresetUpdate(BaseModel):
    """Rename and/or overwrite a preset; a field left out (or null) keeps its value."""

    model_config = ConfigDict(extra="forbid")

    nombre: Optional[Nombre] = None
    payload: Optional[PresetPayload] = None


class PresetItem(BaseModel):
    """One preset as the list shows it; `editable` = the caller may rename, overwrite or delete it."""

    id: int
    vista: Vista
    nombre: str
    compartido: bool
    editable: bool
    payload: PresetPayload
    updated_at: datetime
