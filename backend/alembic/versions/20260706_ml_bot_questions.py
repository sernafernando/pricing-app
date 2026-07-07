"""ml-bot: create ml_bot_questions, ml_bot_config, ml_bot_answer_examples

Revision ID: 20260706_ml_bot
Revises: 20260701_deposito_msg
Create Date: 2026-07-06

Creates the three foundation tables for the MercadoLibre pre-sale question bot
(design §3), seeds `ml_bot_config` with safe defaults (bot fully disabled —
`bot_enabled=false`, `operating_mode=off_hours_only`), seeds the few-shot
`ml_bot_answer_examples` corpus (spec §11), and registers the four
`ml_bot.*` permission codes (R-1001), granted to the admin role only.

No runtime behavior change: nothing reads/writes these tables yet.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260706_ml_bot"
down_revision: Union[str, None] = "20260701_deposito_msg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# ml_bot_config seed defaults (design §3/§11, R-201/R-203/R-901)
# ---------------------------------------------------------------------------
_CONFIG_DEFAULTS: tuple[dict, ...] = (
    {
        "clave": "bot_enabled",
        "valor": "false",
        "descripcion": "Habilita/deshabilita el bot globalmente (R-803)",
        "tipo": "bool",
    },
    {
        "clave": "operating_mode",
        "valor": "off_hours_only",
        "descripcion": "Modo de operacion: off_hours_only | always_on (R-201)",
        "tipo": "string",
    },
    {
        "clave": "business_hours_start",
        "valor": "09:00",
        "descripcion": "Inicio de horario comercial (R-202, inclusivo)",
        "tipo": "time",
    },
    {
        "clave": "business_hours_end",
        "valor": "18:00",
        "descripcion": "Fin de horario comercial (R-202, exclusivo)",
        "tipo": "time",
    },
    {
        "clave": "business_days",
        "valor": "[1,2,3,4,5]",
        "descripcion": "Dias habiles (1=lunes .. 7=domingo)",
        "tipo": "json",
    },
    {
        "clave": "timezone",
        "valor": "America/Argentina/Buenos_Aires",
        "descripcion": "Zona horaria para evaluar horario comercial",
        "tipo": "string",
    },
    {
        "clave": "wait_minutes",
        "valor": "5",
        "descripcion": "Minutos de espera antes de auto-publicar (R-701)",
        "tipo": "int",
    },
    {
        "clave": "wait_minutes_business_hours",
        "valor": "",
        "descripcion": (
            "Ventana de espera alternativa para preguntas en horario comercial "
            "en modo always_on; vacio = usa wait_minutes (R-203)"
        ),
        "tipo": "int",
    },
    {
        "clave": "approx_address",
        "valor": "",
        "descripcion": "Zona aproximada del local (sin direccion exacta, R-402)",
        "tipo": "string",
    },
    {
        "clave": "warm_fallback_template",
        "valor": (
            "¡Hola! Gracias por tu consulta. Nuestro horario de atención es de "
            "{business_hours_start} a {business_hours_end}. Te respondemos apenas abramos."
        ),
        "descripcion": "Mensaje de fallback calido cuando el bot no puede responder (R-601)",
        "tipo": "string",
    },
    {
        "clave": "min_confidence",
        "valor": "0.6",
        "descripcion": "Confianza minima del LLM para publicar sin fallback (R-302)",
        "tipo": "numeric",
    },
    {
        "clave": "llm_model",
        "valor": "llama-3.3-70b-versatile",
        "descripcion": "Modelo Groq usado por GroqProvider",
        "tipo": "string",
    },
    {
        "clave": "poll_interval_seconds",
        "valor": "30",
        "descripcion": "Intervalo (segundos) de los background loops de ingesta/publicacion",
        "tipo": "int",
    },
    {
        "clave": "ingest_cursor_ts",
        "valor": "",
        "descripcion": "Cursor (timestamp) del ultimo webhook de preguntas procesado",
        "tipo": "string",
    },
)

# ---------------------------------------------------------------------------
# ml_bot_answer_examples seed (spec §11 few-shot table, MVP minimum)
# ---------------------------------------------------------------------------
_ANSWER_EXAMPLES: tuple[dict, ...] = (
    {
        "question_example": "¿Tienen stock del modelo azul?",
        "answer_example": (
            "¡Hola! Sí, tenemos stock disponible de ese modelo. Cualquier consulta, "
            "quedamos a disposición."
        ),
        "category": "stock",
        "orden": 1,
    },
    {
        "question_example": "¿Es compatible con el modelo X?",
        "answer_example": (
            "¡Buenas! Sí, es totalmente compatible con ese modelo. Ante cualquier duda, "
            "escribinos."
        ),
        "category": "compatibility",
        "orden": 2,
    },
    {
        "question_example": "¿Cuánto sale?",
        "answer_example": (
            "¡Hola! El precio lo encontrás publicado en la ficha del producto. En caso "
            "de dudas, te respondemos apenas abramos."
        ),
        "category": "fallback",
        "orden": 3,
    },
    {
        "question_example": "¿Cuántas unidades tienen?",
        "answer_example": (
            "¡Hola! Tenemos stock disponible, aunque no compartimos la cantidad exacta. "
            "¡Cualquier consulta quedamos a disposición!"
        ),
        "category": "stock",
        "orden": 4,
    },
    {
        "question_example": "¿Dónde queda el local?",
        "answer_example": (
            "¡Hola! Estamos en la zona de [zona aproximada configurada]. Para más "
            "detalles, te esperamos en horario de atención."
        ),
        "category": "address",
        "orden": 5,
    },
)

# ---------------------------------------------------------------------------
# Permissions (R-1001) — granted to the admin role only, per design §10.
# ---------------------------------------------------------------------------
_PERMISOS_NUEVOS: tuple[dict, ...] = (
    {
        "codigo": "ml_bot.ver",
        "nombre": "Ver panel de preguntas del bot ML",
        "descripcion": "Ver la lista de preguntas pendientes/en espera del bot ML",
        "categoria": "ventas_ml",
        "orden": 500,
        "es_critico": False,
    },
    {
        "codigo": "ml_bot.responder",
        "nombre": "Responder preguntas del bot ML",
        "descripcion": "Tomar control, editar y publicar respuestas del bot ML",
        "categoria": "ventas_ml",
        "orden": 501,
        "es_critico": False,
    },
    {
        "codigo": "ml_bot.config",
        "nombre": "Configurar bot ML",
        "descripcion": "CRUD de variables de configuracion del bot ML",
        "categoria": "ventas_ml",
        "orden": 502,
        "es_critico": True,
    },
    {
        "codigo": "ml_bot.on_off",
        "nombre": "Encender/apagar bot ML",
        "descripcion": "Activar o desactivar globalmente el bot ML",
        "categoria": "ventas_ml",
        "orden": 503,
        "es_critico": True,
    },
)

_ADMIN_ROL_CODIGO = "ADMIN"


def upgrade() -> None:
    op.create_table(
        "ml_bot_questions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ml_question_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("buyer_id", sa.BigInteger(), nullable=True),
        sa.Column("buyer_nickname", sa.String(length=255), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("question_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="received"),
        sa.Column("drafted_answer", sa.Text(), nullable=True),
        sa.Column("answer_source", sa.String(length=10), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("injection_flag", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("wait_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("taken_over_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["taken_over_by"], ["usuarios.id"]),
        sa.UniqueConstraint("ml_question_id", name="uq_ml_bot_questions_ml_question_id"),
    )
    op.create_index("idx_ml_bot_questions_status", "ml_bot_questions", ["status"])
    op.create_index("idx_ml_bot_questions_item_id", "ml_bot_questions", ["item_id"])
    op.create_index("idx_ml_bot_questions_question_date", "ml_bot_questions", ["question_date"])
    op.create_index(
        "idx_ml_bot_questions_wait_until_waiting",
        "ml_bot_questions",
        ["wait_until"],
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_index(
        "idx_ml_bot_questions_taken_over_by", "ml_bot_questions", ["taken_over_by"]
    )

    op.create_table(
        "ml_bot_config",
        sa.Column("clave", sa.String(length=100), nullable=False),
        sa.Column("valor", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("tipo", sa.String(length=50), nullable=True, server_default="string"),
        sa.Column("fecha_modificacion", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("clave"),
    )

    op.create_table(
        "ml_bot_answer_examples",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_example", sa.Text(), nullable=False),
        sa.Column("answer_example", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("orden", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    conn = op.get_bind()

    config_insert = sa.text(
        """
        INSERT INTO ml_bot_config (clave, valor, descripcion, tipo)
        VALUES (:clave, :valor, :descripcion, :tipo)
        ON CONFLICT (clave) DO NOTHING
        """
    )
    for row in _CONFIG_DEFAULTS:
        conn.execute(config_insert, row)

    examples_insert = sa.text(
        """
        INSERT INTO ml_bot_answer_examples (question_example, answer_example, category, orden)
        VALUES (:question_example, :answer_example, :category, :orden)
        """
    )
    for row in _ANSWER_EXAMPLES:
        conn.execute(examples_insert, row)

    permisos_insert = sa.text(
        """
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico)
        ON CONFLICT (codigo) DO NOTHING
        """
    )
    for row in _PERMISOS_NUEVOS:
        conn.execute(permisos_insert, row)

    # Grant the four new codes to the admin role only (idempotent, matches
    # roles_permisos_base uq_rol_permiso unique constraint).
    grant_admin = sa.text(
        """
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = :rol_codigo
          AND p.codigo = ANY(:codigos)
        ON CONFLICT (rol_id, permiso_id) DO NOTHING
        """
    )
    conn.execute(
        grant_admin,
        {
            "rol_codigo": _ADMIN_ROL_CODIGO,
            "codigos": [p["codigo"] for p in _PERMISOS_NUEVOS],
        },
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("DELETE FROM permisos WHERE codigo = ANY(:codigos)"),
        {"codigos": [p["codigo"] for p in _PERMISOS_NUEVOS]},
    )

    op.drop_table("ml_bot_answer_examples")
    op.drop_table("ml_bot_config")

    op.drop_index("idx_ml_bot_questions_taken_over_by", table_name="ml_bot_questions")
    op.drop_index("idx_ml_bot_questions_wait_until_waiting", table_name="ml_bot_questions")
    op.drop_index("idx_ml_bot_questions_question_date", table_name="ml_bot_questions")
    op.drop_index("idx_ml_bot_questions_item_id", table_name="ml_bot_questions")
    op.drop_index("idx_ml_bot_questions_status", table_name="ml_bot_questions")
    op.drop_table("ml_bot_questions")
