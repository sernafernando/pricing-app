"""Seed textos predefinidos de sanciones con modelos comunes

Revision ID: 20260327_seed_textos_pred
Revises: 20260327_texto_pred_sancion
Create Date: 2026-03-27
"""

from alembic import op

revision = "20260327_seed_textos_pred"
down_revision = "20260327_texto_pred_sancion"
branch_labels = None
depends_on = None


TEXTOS = [
    {
        "nombre": "Llegada tarde",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que en el dia {fecha_sancion} ha incurrido en "
            "llegada tarde a su puesto de trabajo, incumpliendo el horario de ingreso "
            "establecido.\n\n"
            "Se le recuerda que el cumplimiento del horario es una obligacion contractual "
            "y que la reiteracion de esta conducta dara lugar a sanciones de mayor gravedad."
        ),
        "orden": 1,
    },
    {
        "nombre": "Falta injustificada",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que se ha registrado su inasistencia sin "
            "justificacion el dia {fecha_sancion}.\n\n"
            "Se le informa que las faltas injustificadas constituyen un incumplimiento "
            "a las obligaciones laborales vigentes. La reiteracion de esta conducta "
            "podra dar lugar a sanciones disciplinarias de mayor gravedad, conforme "
            "a la legislacion laboral aplicable."
        ),
        "orden": 2,
    },
    {
        "nombre": "Incumplimiento de tareas",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que en el dia {fecha_sancion} ha incurrido en "
            "incumplimiento de las tareas asignadas a su puesto de trabajo.\n\n"
            "Detalle: {detalle_incumplimiento}\n\n"
            "Se le recuerda que el cumplimiento de las tareas asignadas es parte "
            "esencial de sus obligaciones contractuales."
        ),
        "orden": 3,
    },
    {
        "nombre": "Falta de respeto",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que en el dia {fecha_sancion} ha incurrido en "
            "una conducta inapropiada consistente en falta de respeto hacia "
            "{persona_afectada}.\n\n"
            "Detalle: {detalle_incidente}\n\n"
            "Se le recuerda que el respeto mutuo y el buen trato son valores "
            "fundamentales de esta organizacion. La reiteracion de esta conducta "
            "dara lugar a sanciones de mayor gravedad."
        ),
        "orden": 4,
    },
    {
        "nombre": "Uso indebido de elementos de trabajo",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que en el dia {fecha_sancion} se ha constatado "
            "el uso indebido de elementos de trabajo provistos por la empresa.\n\n"
            "Detalle: {detalle_uso_indebido}\n\n"
            "Se le recuerda que los elementos de trabajo son propiedad de la empresa "
            "y deben ser utilizados exclusivamente para los fines laborales asignados."
        ),
        "orden": 5,
    },
    {
        "nombre": "Abandono de puesto",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que en el dia {fecha_sancion} ha abandonado "
            "su puesto de trabajo sin autorizacion previa de su superior.\n\n"
            "Se le informa que el abandono de puesto constituye una falta grave "
            "que compromete el normal funcionamiento del area y la seguridad "
            "de las operaciones. La reiteracion de esta conducta podra dar lugar "
            "a sanciones disciplinarias de mayor gravedad."
        ),
        "orden": 6,
    },
    {
        "nombre": "Incumplimiento de normas de seguridad",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que en el dia {fecha_sancion} ha incurrido en "
            "el incumplimiento de las normas de seguridad e higiene vigentes.\n\n"
            "Detalle: {detalle_incumplimiento_seguridad}\n\n"
            "Se le recuerda que el cumplimiento de las normas de seguridad es "
            "obligatorio y su inobservancia pone en riesgo su integridad fisica "
            "y la de sus compañeros de trabajo."
        ),
        "orden": 7,
    },
    {
        "nombre": "Suspension disciplinaria",
        "texto": (
            "Por medio de la presente se notifica a {nombre_empleado}, "
            "Legajo N° {legajo}, DNI {dni}, que se desempeña en el area de {area} "
            "en el puesto de {puesto}, que atento a los antecedentes disciplinarios "
            "obrantes en su legajo y a la gravedad de los hechos acontecidos, "
            "se ha resuelto aplicarle una suspension disciplinaria de {dias_suspension} "
            "dias corridos, a cumplirse desde el {fecha_desde} hasta el {fecha_hasta} "
            "inclusive.\n\n"
            "Durante el periodo de suspension no debera presentarse a trabajar "
            "y no percibira haberes por los dias no trabajados, conforme a lo "
            "establecido en la legislacion laboral vigente."
        ),
        "orden": 8,
    },
]


def upgrade():
    for t in TEXTOS:
        nombre = t["nombre"].replace("'", "''")
        texto = t["texto"].replace("'", "''")
        op.execute(f"""
            INSERT INTO rrhh_texto_predefinido_sancion (nombre, texto, activo, orden)
            VALUES ('{nombre}', '{texto}', true, {t["orden"]})
            ON CONFLICT (nombre) DO UPDATE SET
                texto = EXCLUDED.texto,
                orden = EXCLUDED.orden,
                activo = true;
        """)


def downgrade():
    nombres = ", ".join(f"'{t['nombre']}'" for t in TEXTOS)
    op.execute(f"DELETE FROM rrhh_texto_predefinido_sancion WHERE nombre IN ({nombres});")
