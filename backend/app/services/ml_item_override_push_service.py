"""Push a publication's local override to ML ("Actualizar en ML", Publicaciones ML T8c), through the ml-webhook proxy.

The owner's rule (L20): editing never writes ML; pushing is a separate button, and "no siempre se puede modificar en
ml". So only what differs from ML's data is sent, and only what ML lets change; every field left out is named with
its reason. ML's rules (developers site, "Sincroniza y modifica publicaciones"): an active or paused publication takes
pictures and a description; the title only while it has no sales; a catalog publication is not modified.

Order: kill switch -> the store's item, override and original on a short session -> the plan -> the item fields
(`title`, `pictures`, `attributes`) in one write and the description in another, each once, never retried -> an
`ml_write_log` row with the user per confirmed write -> a manual-lane re-read of the item and its description after
anything that may have landed, so the original catches up with ML.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import exists, select
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_item_override import MlItemOverride
from app.models.ml_publications import MlItem, MlItemVariation
from app.models.ml_write_log import ACTION_UPDATE_DATA, ACTION_UPDATE_DESCRIPTION, RESOURCE_ITEM, MlWriteLog
from app.services.ml_item_override_service import FIELDS
from app.services.ml_publications import queue as ml_pub_queue
from app.services.ml_publications.publication_data import publication_data
from app.services.ml_publications.resources import CORE_RESOURCE
from app.services.ml_webhook_client import MLWebhookClient

logger = logging.getLogger(__name__)

# The outcome of a push.
SENT = "sent"  # at least one write reached ML or may have: each field says how it went
NOTHING = "nothing"  # nothing differs from ML, or nothing that differs can go
DISABLED = "disabled"
NOT_FOUND = "not_found"
NOT_ELIGIBLE = "not_eligible"
UNKNOWN_STATUS = "unknown_status"  # the store could not be read: nothing is written blind

# Each field's state.
SUBMITTED = "submitted"
REJECTED = "rejected"
AMBIGUOUS = "ambiguous"
NOT_SENT = "not_sent"  # the proxy refused to forward it: ML never saw it
OMITTED = "omitted"  # ML does not let it change: not sent

MODIFIABLE_STATUSES = ("active", "paused")
DESCRIPTION_RESOURCE = "description"

_AMBIGUOUS_MESSAGE = "No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar."


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


@dataclass(frozen=True)
class Parte:
    campo: str
    estado: str
    motivo: Optional[str]


@dataclass(frozen=True)
class PushOutcome:
    status: str
    message: Optional[str]
    partes: tuple[Parte, ...]


@dataclass(frozen=True)
class Stored:
    found: bool
    facts: Optional[PushFacts]
    original: Optional[dict[str, Any]]
    override: Optional[dict[str, Any]]  # None: nothing overridden


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


_BODY_FIELDS = (("title", "titulo"), ("pictures", "fotos"), ("attributes", "atributos"))


async def push_override(mla: str, usuario_id: Optional[int]) -> PushOutcome:
    if not settings.ML_ITEM_DATA_WRITE_ENABLED:
        return PushOutcome(DISABLED, "Actualizar publicaciones en Mercado Libre está deshabilitado.", ())

    stored = await run_in_threadpool(_read, mla)
    if stored is None:
        return PushOutcome(UNKNOWN_STATUS, "No se pudo leer la publicación: probá de nuevo.", ())
    if not stored.found:
        return PushOutcome(NOT_FOUND, f"No se encontró la publicación {mla}", ())
    plan = plan_push(stored.facts, stored.original, stored.override)
    if plan.refused is not None:
        return PushOutcome(NOT_ELIGIBLE, plan.refused, ())
    omitted = tuple(Parte(campo, OMITTED, motivo) for campo, motivo in plan.omitidos)
    if not plan.item_body and plan.descripcion is None:
        return PushOutcome(NOTHING, "No hay cambios para enviar a Mercado Libre.", omitted)

    client = MLWebhookClient()
    partes: list[Parte] = []
    landed = False
    if plan.item_body:
        result = await client.put_item_data(mla, plan.item_body)
        estado, motivo = _verdict(result, "data_write")
        partes += [Parte(campo, estado, motivo) for key, campo in _BODY_FIELDS if key in plan.item_body]
        if estado == SUBMITTED:
            await run_in_threadpool(_record_write_log, mla, ACTION_UPDATE_DATA, plan.item_body, usuario_id)
        landed = landed or estado in (SUBMITTED, AMBIGUOUS)
    if plan.descripcion is not None:
        result = await client.put_item_description(mla, plan.descripcion)
        estado, motivo = _verdict(result, "description_write")
        partes.append(Parte("descripcion", estado, motivo))
        if estado == SUBMITTED:
            payload = {"plain_text": plan.descripcion}
            await run_in_threadpool(_record_write_log, mla, ACTION_UPDATE_DESCRIPTION, payload, usuario_id)
        landed = landed or estado in (SUBMITTED, AMBIGUOUS)
    if landed:
        await run_in_threadpool(_enqueue_refresh_safely, mla)
    if all(parte.estado == NOT_SENT for parte in partes):
        message = "Ningún cambio llegó a Mercado Libre: el servicio de escritura lo rechazó."
        return PushOutcome(NOT_SENT, message, tuple(partes) + omitted)
    return PushOutcome(SENT, None, tuple(partes) + omitted)


def _verdict(result: dict, stamp: str) -> tuple[str, Optional[str]]:
    if result["ok"]:
        return SUBMITTED, None
    if result["ambiguous"]:
        return AMBIGUOUS, _AMBIGUOUS_MESSAGE
    body = result["body"] if isinstance(result["body"], dict) else {}
    if body.get(stamp) == "not_attempted":
        return NOT_SENT, "El cambio no se envió: el servicio de escritura lo rechazó."
    return REJECTED, body.get("message") or "Mercado Libre rechazó el cambio."


def _read(mla: str) -> Optional[Stored]:
    """The publication's facts, original and override; None when the store cannot be read."""
    try:
        with get_background_db() as db:
            item = db.get(MlItem, mla)
            if item is None:
                return Stored(False, None, None, None)
            row = db.get(MlItemOverride, mla)
            has_variations = db.scalar(select(exists().where(MlItemVariation.item_id == mla)))
            return Stored(
                found=True,
                facts=PushFacts(
                    status=item.status,
                    deleted=item.gone_at is not None or "deleted" in (item.sub_status or []),
                    catalog_listing=bool(item.catalog_listing),
                    sold_quantity=item.sold_quantity or 0,
                    has_variations=bool(has_variations),
                ),
                original=publication_data(db, item),
                override=None if row is None else {field: getattr(row, field) for field in FIELDS},
            )
    except Exception as e:
        logger.error("store read failed for mla=%s before an override push: %s", mla, e)
        return None


def _record_write_log(mla: str, action: str, payload: dict, usuario_id: Optional[int]) -> None:
    """The write already happened at ML: a failure here is logged, never raised."""
    try:
        with get_background_db() as db:
            db.add(MlWriteLog(mla=mla, resource=RESOURCE_ITEM, action=action, payload=payload, usuario_id=usuario_id))
    except Exception as e:
        logger.error(
            "ml_write_log insert failed for mla=%s action=%s (the write at ML is unaffected): %s", mla, action, e
        )


def _enqueue_refresh(mla: str) -> None:
    ml_pub_queue.enqueue(
        [
            ml_pub_queue.EnqueueEntry(
                kind="item",
                entity_id=mla,
                lane=ml_pub_queue.LANE_MANUAL,
                resources=(CORE_RESOURCE, DESCRIPTION_RESOURCE),
            )
        ]
    )


def _enqueue_refresh_safely(mla: str) -> None:
    try:
        _enqueue_refresh(mla)
    except Exception as e:
        logger.error("refresh enqueue failed for mla=%s after an override push: %s", mla, e)
