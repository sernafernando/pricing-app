"""ml-bot: seed editable business-text config defaults + in-hours fallback variant

Revision ID: 20260708_ml_bot_defs
Revises: 20260707_ml_bot_prov
Create Date: 2026-07-08

Seeds `ml_bot_config` with sensible defaults for the operator-editable
business-text keys, so they appear in the panel's config list from day one
(operator feedback: hardcoded defaults were invisible until the operator
typed the key name from memory). Also introduces the in-hours fallback
template variant `warm_fallback_template_business_hours` so the bot can
pick a shorter message during working hours (no need to repeat the
schedule that's already implicit).

ALL inserts use `ON CONFLICT (clave) DO NOTHING` — existing operator
customizations are NEVER overwritten. Fresh deployments get the defaults;
running deployments only get keys that were previously absent.

Store IDs seeded in `answer_signatures_by_store`:
- 57997: Gauss Online (own official store) — appended signature includes
  the store URL so buyers can browse the catalog.
- 2645: TP-Link (third-party official store) — empty signature (no Gauss
  branding inside another brand's store).
Publications in an official store WITHOUT a map entry get NO signature
(fail-safe: better silent than wrong-store-signed).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260708_ml_bot_defs"
down_revision: Union[str, None] = "20260707_ml_bot_prov"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEEDS = [
    {
        "clave": "warm_fallback_template",
        "valor": (
            "¡Hola! No tengo esa información en este momento. "
            "Volvé a escribirnos {attention_hours} y con gusto te averiguamos. "
            "¡Gracias!"
        ),
        "descripcion": (
            "Mensaje de fallback cuando el bot no puede responder Y estamos "
            "FUERA del horario laboral. Usa {attention_hours} como placeholder "
            "para el texto de horarios (attention_hours_text)."
        ),
        "tipo": "string",
    },
    {
        "clave": "warm_fallback_template_business_hours",
        "valor": (
            "¡Hola! No tengo esa información en este momento. "
            "Volvé a consultar más tarde y te averiguamos. ¡Gracias!"
        ),
        "descripcion": (
            "Mensaje de fallback cuando el bot no puede responder Y estamos "
            "DENTRO del horario laboral (no repite horarios, solo pide que "
            "vuelva más tarde)."
        ),
        "tipo": "string",
    },
    {
        "clave": "attention_hours_text",
        "valor": "de lunes a viernes de 9 a 18 hs y sábados de 9 a 13 hs",
        "descripcion": (
            "Texto libre de horarios de atención que el bot le dice al "
            "comprador (se inyecta al placeholder {attention_hours} del "
            "template de fallback fuera de horario)."
        ),
        "tipo": "string",
    },
    {
        "clave": "answer_company_signature",
        "valor": "Somos Gauss Online",
        "descripcion": (
            "Firma default de la empresa que se appendea a las respuestas del "
            "bot en publicaciones SIN tienda oficial. Para tiendas oficiales "
            "usar answer_signatures_by_store."
        ),
        "tipo": "string",
    },
    {
        "clave": "answer_signatures_by_store",
        "valor": (
            '{"57997": "Podés ver más productos en nuestra tienda oficial: '
            "https://www.mercadolibre.com.ar/tienda/gaussonline"
            '", "2645": ""}'
        ),
        "descripcion": (
            "Firmas por tienda oficial (JSON: {official_store_id: texto}). "
            "\"\" = sin firma para esa tienda. Publicaciones en tiendas "
            "oficiales SIN entrada en el mapa → sin firma (fail-safe: mejor "
            "no firmar que firmar mal en tienda ajena)."
        ),
        "tipo": "string",
    },
    {
        "clave": "answer_closing_text",
        "valor": "",
        "descripcion": (
            "Saludo/cierre optativo que se appendea a las respuestas del bot "
            "(ej. \"¡Cualquier otra consulta, escribinos!\"). Vacío = "
            "desactivado."
        ),
        "tipo": "string",
    },
    {
        "clave": "llm_providers",
        "valor": (
            '[{"name": "groq", "model": "llama-3.3-70b-versatile", "enabled": true}, '
            '{"name": "cerebras", "model": "llama-3.3-70b", "enabled": true}, '
            '{"name": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "enabled": true}]'
        ),
        "descripcion": (
            "Roster de proveedores LLM (JSON list de {name, model, enabled}). "
            "Round-robin por pregunta + failover en cadena (si el primero "
            "agota reintentos, prueba el siguiente antes del warm fallback). "
            "Ausente/malformado → fail-safe a Groq-only. Requiere que las API "
            "keys (GROQ_API_KEY / CEREBRAS_API_KEY / OPENROUTER_API_KEY) "
            "estén configuradas en el .env — proveedor sin key se saltea con "
            "warning."
        ),
        "tipo": "string",
    },
    {
        "clave": "work_schedule",
        "valor": (
            '{"1": ["09:00", "18:00"], "2": ["09:00", "18:00"], '
            '"3": ["09:00", "18:00"], "4": ["09:00", "18:00"], '
            '"5": ["09:00", "18:00"], "6": ["09:00", "13:00"]}'
        ),
        "descripcion": (
            "Horario laboral por día (JSON: {isoweekday 1-7: [start, end]}). "
            "Día ausente = no laborable. Semántica [start,end): 13:00 exacto "
            "queda FUERA del horario. Si el JSON es inválido, se usa el "
            "legacy business_days + business_hours_start/end."
        ),
        "tipo": "string",
    },
]


_SEEDED_KEYS = tuple(s["clave"] for s in _SEEDS)


def upgrade() -> None:
    conn = op.get_bind()
    for seed in _SEEDS:
        conn.execute(
            sa.text(
                """
                INSERT INTO ml_bot_config (clave, valor, descripcion, tipo)
                VALUES (:clave, :valor, :descripcion, :tipo)
                ON CONFLICT (clave) DO NOTHING
                """
            ),
            seed,
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM ml_bot_config WHERE clave = ANY(:claves)"),
        {"claves": list(_SEEDED_KEYS)},
    )
