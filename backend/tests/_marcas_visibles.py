"""The brands-without-stock exception table for real-Postgres fixtures whose schema has no `usuarios`: every brand
option list reads it (`app.services.marcas_visibles`). Same columns as the model, no user foreign key."""

MARCAS_VISIBLES_DDL = (
    "CREATE TABLE IF NOT EXISTS marcas_visibles_excepciones (id SERIAL PRIMARY KEY, marca VARCHAR(100) NOT NULL "
    "UNIQUE, creado_por_id INTEGER, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)
