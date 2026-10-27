"""What a publication's local override can push to ML ("Actualizar en ML", Publicaciones ML T8c).

The owner's rule (L20): editing never writes ML; pushing is a separate button, and "no siempre se puede modificar en
ml". So only what differs from ML's data is sent, and only what ML lets change; every field left out is named with
its reason. ML's rules (developers site, "Sincroniza y modifica publicaciones"): an active or paused publication takes
pictures and a description; the title only while it has no sales; a catalog publication is not modified.

`plan_push` is that decision, pure; the write through the ml-webhook proxy builds on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

MODIFIABLE_STATUSES = ("active", "paused")


@dataclass(frozen=True)
class PushFacts:
    """What ML's rules depend on, as the store last read it."""

    status: Optional[str]
    deleted: bool
    catalog_listing: bool
    sold_quantity: int
    has_variations: bool


@dataclass(frozen=True)
class PushPlan:
    refused: Optional[str]  # the whole publication cannot be modified at ML
    item_body: dict[str, Any]  # the item fields to write, in ML's names
    descripcion: Optional[str]  # the description to write, None for none
    omitidos: tuple[tuple[str, str], ...]  # (field, reason) of what differs but cannot go


def _refusal(facts: PushFacts) -> Optional[str]:
    if facts.deleted:
        return "La publicación está eliminada."
    if facts.catalog_listing:
        return "Las publicaciones de catálogo no se pueden modificar en Mercado Libre."
    if facts.status not in MODIFIABLE_STATUSES:
        return f"Una publicación en estado {facts.status} no se puede modificar."
    return None


def plan_push(facts: PushFacts, original: dict[str, Any], override: Optional[dict[str, Any]]) -> PushPlan:
    """What to send: the overridden fields that differ from ML's data and that ML lets change."""
    refused = _refusal(facts)
    if refused is not None or override is None:
        return PushPlan(refused, {}, None, ())
    body: dict[str, Any] = {}
    omitidos: list[tuple[str, str]] = []

    titulo = override["titulo"]
    if titulo is not None and titulo != original["titulo"]:
        if facts.sold_quantity > 0:
            omitidos.append(("titulo", "La publicación tiene ventas: Mercado Libre no deja cambiar el título."))
        else:
            body["title"] = titulo

    fotos = override["fotos"]
    if fotos is not None and [f["id"] for f in fotos] != [f["id"] for f in original["fotos"]]:
        if facts.has_variations:
            omitidos.append(
                ("fotos", "La publicación tiene variaciones: las fotos se cambian en Mercado Libre, por variación.")
            )
        else:
            body["pictures"] = [{"id": foto["id"]} for foto in fotos]

    atributos = override["atributos"]
    if atributos is not None:
        current = {atributo["id"]: atributo["value_name"] for atributo in original["atributos"]}
        changed = [
            {"id": atributo["id"], "value_name": atributo["value_name"]}
            for atributo in atributos
            if current.get(atributo["id"]) != atributo["value_name"]
        ]
        if changed:
            body["attributes"] = changed
        kept = {atributo["id"] for atributo in atributos}
        dropped = [
            atributo["name"] or atributo["id"] for atributo in original["atributos"] if atributo["id"] not in kept
        ]
        if dropped:
            omitidos.append(
                ("atributos", f"Los atributos quitados no se borran en Mercado Libre: {', '.join(dropped)}.")
            )

    descripcion = None
    if override["descripcion"] is not None and override["descripcion"] != (original["descripcion"] or ""):
        if override["descripcion"].strip():
            descripcion = override["descripcion"]
        else:
            omitidos.append(("descripcion", "Mercado Libre no acepta una descripción vacía."))

    return PushPlan(None, body, descripcion, tuple(omitidos))
