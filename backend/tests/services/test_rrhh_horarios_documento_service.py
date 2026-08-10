"""Reglas de negocio del documento de horarios (`HorariosDocumentoService`).

Cubre las decisiones que RRHH ya tomó y que el documento impreso no puede
traicionar: primera/última fichada, hora Argentina, días hábiles, y el tope de
rango de los reportes hermanos.

Nota sobre timezone en tests: el SQLite de `conftest` descarta el offset de las
columnas `DateTime(timezone=True)`, así que un timestamp guardado aware vuelve
naive. El servicio normaliza los naive a UTC (ver `_a_utc`), que es exactamente
como los escribe el sync Hikvision — con lo cual estos tests ejercitan el mismo
camino de conversión que producción.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from fastapi import HTTPException

from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
from app.models.rrhh_presentismo import RRHHPresentismoDiario
from app.services.rrhh_horarios_documento_service import (
    MAX_RANGO_DIAS,
    HorariosDocumentoService,
)

# Semana de referencia: 2026-08-03 es lunes, 2026-08-08 sábado, 2026-08-09 domingo.
LUNES = date(2026, 8, 3)
MARTES = date(2026, 8, 4)
SABADO = date(2026, 8, 8)
DOMINGO = date(2026, 8, 9)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def empleado(db) -> RRHHEmpleado:
    """Empleado vigente, sin turno asignado todavía."""
    emp = RRHHEmpleado(
        nombre="Juan",
        apellido="Pérez",
        dni="30111222",
        cuil="20301112223",
        legajo="0042",
        fecha_ingreso=date(2020, 1, 1),
        puesto="Operario",
        area="Depósito",
        estado="activo",
        activo=True,
    )
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def turno_lun_vie(db) -> RRHHHorarioConfig:
    horario = RRHHHorarioConfig(
        nombre="Turno Mañana",
        hora_entrada=time(9, 0),
        hora_salida=time(18, 0),
        tolerancia_minutos=15,
        dias_semana="1,2,3,4,5",
        activo=True,
    )
    db.add(horario)
    db.flush()
    return horario


@pytest.fixture()
def empleado_lun_vie(db, empleado, turno_lun_vie) -> RRHHEmpleado:
    db.add(RRHHEmpleadoHorario(empleado_id=empleado.id, horario_config_id=turno_lun_vie.id, prioridad=1))
    db.flush()
    return empleado


@pytest.fixture()
def svc(db) -> HorariosDocumentoService:
    return HorariosDocumentoService(db)


def _fichada(db, empleado: RRHHEmpleado, ts_utc: datetime, tipo: str = "entrada") -> None:
    """Inserta una fichada con timestamp UTC explícito."""
    db.add(
        RRHHFichada(
            empleado_id=empleado.id,
            timestamp=ts_utc,
            tipo=tipo,
            origen="hikvision",
        )
    )
    db.flush()


def _dias(resultado: dict, fecha: date) -> dict:
    """Extrae el renglón de un día puntual del primer empleado."""
    dias = resultado["empleados"][0]["dias"]
    match = [d for d in dias if d["fecha"] == fecha.isoformat()]
    assert match, f"Se esperaba el día {fecha} en {[d['fecha'] for d in dias]}"
    return match[0]


# ---------------------------------------------------------------------------
# Regla 1: entrada = primera fichada, salida = última, `tipo` no se usa
# ---------------------------------------------------------------------------


def test_tres_fichadas_usa_primera_y_ultima_e_ignora_la_intermedia(db, svc, empleado_lun_vie):
    """Con 3 fichadas la intermedia se ignora y no se descuenta almuerzo.

    Los `tipo` están deliberadamente mal etiquetados (el sync Hikvision alterna
    por orden de timestamp): la última queda como 'entrada'. Si el servicio
    confiara en `tipo`, no encontraría salida y el día saldría incompleto.
    """
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 11, 57, tzinfo=timezone.utc), tipo="entrada")
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc), tipo="salida")
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 21, 3, tzinfo=timezone.utc), tipo="entrada")

    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert dia["entrada"] == "08:57"
    assert dia["salida"] == "18:03"
    assert dia["horas_hhmm"] == "09:06"
    assert dia["horas_decimal"] == 9.1
    assert dia["incompleto"] is False
    assert dia["sin_fichadas"] is False
    assert dia["estado"] == "presente"


def test_totales_del_empleado_suman_los_dias(db, svc, empleado_lun_vie):
    # Lunes 8h, martes 7h30.
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 4, 19, 30, tzinfo=timezone.utc))

    emp = svc.horarios_documento(LUNES, MARTES)["empleados"][0]

    assert emp["total_horas_hhmm"] == "15:30"
    assert emp["total_horas_decimal"] == 15.5
    assert emp["total_dias"] == 2
    assert emp["dias_trabajados"] == 2
    assert emp["legajo"] == "0042"
    assert emp["nombre_completo"] == "Pérez, Juan"
    assert emp["dni"] == "30111222"
    assert emp["cuil"] == "20301112223"
    assert emp["puesto"] == "Operario"
    assert emp["area"] == "Depósito"


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------


def test_fichada_en_utc_se_formatea_en_hora_argentina(db, svc, empleado_lun_vie):
    """11:57 UTC es 08:57 ART. Sin conversión el documento saldría +3h."""
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 11, 57, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 21, 3, tzinfo=timezone.utc))

    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert (dia["entrada"], dia["salida"]) == ("08:57", "18:03")


def test_turno_nocturno_se_agrupa_en_el_dia_ART_no_en_el_UTC(db, svc, empleado_lun_vie):
    """Un turno que termina pasada la medianoche UTC sigue siendo el mismo día ART.

    Entrada 2026-08-03 22:00 UTC (= 19:00 del lunes ART) y salida
    2026-08-04 01:30 UTC (= 22:30 del *lunes* ART). Agrupando en UTC caerían
    en días distintos y el lunes quedaría incompleto y el martes también.
    """
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 22, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 4, 1, 30, tzinfo=timezone.utc))

    resultado = svc.horarios_documento(LUNES, MARTES)

    lunes = _dias(resultado, LUNES)
    assert (lunes["entrada"], lunes["salida"]) == ("19:00", "22:30")
    assert lunes["horas_hhmm"] == "03:30"
    assert lunes["incompleto"] is False

    martes = _dias(resultado, MARTES)
    assert martes["sin_fichadas"] is True
    assert (martes["entrada"], martes["salida"]) == ("", "")


def test_fichada_del_dia_anterior_UTC_pertenece_al_dia_ART_pedido(db, svc, empleado_lun_vie):
    """2026-08-04 02:00 UTC es 2026-08-03 23:00 ART: entra en el rango del lunes.

    Prueba que la ventana SQL se abre lo suficiente y que el recorte se hace
    después de convertir a ART.
    """
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 4, 2, 0, tzinfo=timezone.utc))

    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert (dia["entrada"], dia["salida"]) == ("17:00", "23:00")


# ---------------------------------------------------------------------------
# Días incompletos / sin fichadas
# ---------------------------------------------------------------------------


def test_una_sola_fichada_deja_el_dia_incompleto_sin_horas(db, svc, empleado_lun_vie):
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 11, 57, tzinfo=timezone.utc))

    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert dia["entrada"] == "08:57"
    assert dia["salida"] == ""
    assert dia["horas_decimal"] == 0.0
    assert dia["horas_hhmm"] == "00:00"
    assert dia["incompleto"] is True
    assert dia["sin_fichadas"] is False


def test_dia_habil_sin_fichadas_muestra_el_estado_de_presentismo(db, svc, empleado_lun_vie):
    db.add(
        RRHHPresentismoDiario(
            empleado_id=empleado_lun_vie.id,
            fecha=LUNES,
            estado="vacaciones",
        )
    )
    db.flush()

    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert dia["estado"] == "vacaciones"
    assert (dia["entrada"], dia["salida"]) == ("", "")
    assert dia["horas_decimal"] == 0.0
    assert dia["sin_fichadas"] is True
    assert dia["incompleto"] is False


def test_dia_habil_sin_fichadas_ni_presentismo_cae_en_ausente(db, svc, empleado_lun_vie):
    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert dia["estado"] == "ausente"
    assert dia["sin_fichadas"] is True


# ---------------------------------------------------------------------------
# Regla 2: qué días entran
# ---------------------------------------------------------------------------


def test_sabado_trabajado_fuera_de_turno_se_incluye(db, svc, empleado_lun_vie):
    """El turno es Lun-Vie, pero si hubo fichadas el sábado no se puede ocultar."""
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 8, 16, 0, tzinfo=timezone.utc))

    resultado = svc.horarios_documento(SABADO, DOMINGO)
    dias = resultado["empleados"][0]["dias"]

    assert [d["fecha"] for d in dias] == [SABADO.isoformat()]
    sabado = dias[0]
    assert (sabado["entrada"], sabado["salida"]) == ("09:00", "13:00")
    assert sabado["dia_semana"] == "Sáb"
    assert sabado["fecha_label"] == "08/08"


def test_fin_de_semana_sin_fichadas_no_aparece(db, svc, empleado_lun_vie):
    resultado = svc.horarios_documento(SABADO, DOMINGO)

    assert resultado["empleados"][0]["dias"] == []
    assert resultado["empleados"][0]["total_dias"] == 0


def test_feriado_sin_fichadas_no_aparece(db, svc, empleado_lun_vie):
    db.add(
        RRHHHorarioExcepcion(
            fecha=LUNES,
            tipo="feriado",
            descripcion="Feriado de prueba",
            es_laborable=False,
        )
    )
    db.flush()

    resultado = svc.horarios_documento(LUNES, MARTES)
    dias = resultado["empleados"][0]["dias"]

    assert [d["fecha"] for d in dias] == [MARTES.isoformat()]


def test_feriado_con_fichadas_si_aparece(db, svc, empleado_lun_vie):
    db.add(
        RRHHHorarioExcepcion(
            fecha=LUNES,
            tipo="feriado",
            descripcion="Feriado de prueba",
            es_laborable=False,
        )
    )
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 20, 0, tzinfo=timezone.utc))

    dia = _dias(svc.horarios_documento(LUNES, LUNES), LUNES)

    assert dia["horas_hhmm"] == "08:00"


def test_empleado_sin_turno_asignado_usa_fallback_lunes_a_viernes(db, svc, empleado):
    """Sin `RRHHEmpleadoHorario`, el rango hábil es Lun-Vie."""
    resultado = svc.horarios_documento(LUNES, DOMINGO)
    fechas = [d["fecha"] for d in resultado["empleados"][0]["dias"]]

    assert fechas == [date(2026, 8, d).isoformat() for d in (3, 4, 5, 6, 7)]


def test_turno_que_incluye_sabado_lo_agenda_sin_fichadas(db, svc, empleado):
    turno = RRHHHorarioConfig(
        nombre="Turno Sábado",
        hora_entrada=time(9, 0),
        hora_salida=time(13, 0),
        tolerancia_minutos=15,
        dias_semana="6",
        activo=True,
    )
    db.add(turno)
    db.flush()
    db.add(RRHHEmpleadoHorario(empleado_id=empleado.id, horario_config_id=turno.id, prioridad=1))
    db.flush()

    resultado = svc.horarios_documento(LUNES, DOMINGO)
    fechas = [d["fecha"] for d in resultado["empleados"][0]["dias"]]

    assert fechas == [SABADO.isoformat()]


# ---------------------------------------------------------------------------
# Filtros y validación
# ---------------------------------------------------------------------------


def test_empleado_ids_filtra_el_resultado(db, svc, empleado_lun_vie):
    otro = RRHHEmpleado(
        nombre="Ana",
        apellido="Álvarez",
        dni="28999888",
        legajo="0043",
        fecha_ingreso=date(2021, 1, 1),
        estado="activo",
        activo=True,
    )
    db.add(otro)
    db.flush()

    todos = svc.horarios_documento(LUNES, LUNES)
    filtrado = svc.horarios_documento(LUNES, LUNES, empleado_ids=[empleado_lun_vie.id])

    assert {e["empleado_id"] for e in todos["empleados"]} == {empleado_lun_vie.id, otro.id}
    assert [e["empleado_id"] for e in filtrado["empleados"]] == [empleado_lun_vie.id]


def test_empleado_dado_de_baja_se_excluye(db, svc, empleado_lun_vie):
    empleado_lun_vie.estado = "baja"
    empleado_lun_vie.activo = False
    db.flush()

    assert svc.horarios_documento(LUNES, LUNES)["empleados"] == []


def test_rango_mayor_al_tope_se_rechaza(svc):
    desde = date(2026, 1, 1)
    hasta = desde.fromordinal(desde.toordinal() + MAX_RANGO_DIAS + 1)

    with pytest.raises(HTTPException) as exc:
        svc.horarios_documento(desde, hasta)

    assert exc.value.status_code == 400
    assert "62" in exc.value.detail


def test_rango_en_el_tope_exacto_se_acepta(svc):
    desde = date(2026, 1, 1)
    hasta = desde.fromordinal(desde.toordinal() + MAX_RANGO_DIAS)

    resultado = svc.horarios_documento(desde, hasta)

    assert resultado["fecha_desde"] == desde.isoformat()
    assert resultado["fecha_hasta"] == hasta.isoformat()


def test_rango_invertido_se_rechaza(svc):
    with pytest.raises(HTTPException) as exc:
        svc.horarios_documento(MARTES, LUNES)

    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Performance: nada de N+1
# ---------------------------------------------------------------------------


def test_no_hay_N_mas_1_al_crecer_empleados_y_dias(db, svc, turno_lun_vie, query_counter):
    """El conteo de SELECT no depende de la cantidad de empleados ni de días."""
    for i in range(5):
        emp = RRHHEmpleado(
            nombre=f"Emp{i}",
            apellido=f"Apellido{i}",
            dni=f"4000000{i}",
            legajo=f"010{i}",
            fecha_ingreso=date(2020, 1, 1),
            estado="activo",
            activo=True,
        )
        db.add(emp)
        db.flush()
        db.add(RRHHEmpleadoHorario(empleado_id=emp.id, horario_config_id=turno_lun_vie.id, prioridad=1))
        for dia in range(3, 8):
            _fichada(db, emp, datetime(2026, 8, dia, 12, 0, tzinfo=timezone.utc))
            _fichada(db, emp, datetime(2026, 8, dia, 20, 0, tzinfo=timezone.utc))

    with query_counter() as counter:
        svc.horarios_documento(LUNES, date(2026, 8, 31))

    selects = [s for s in counter.statements if s.strip().upper().startswith("SELECT")]
    assert len(selects) == 5, selects


# ---------------------------------------------------------------------------
# Endpoint GET /api/rrhh/reportes/horarios-documento
# ---------------------------------------------------------------------------

ENDPOINT = "/api/rrhh/reportes/horarios-documento"


@pytest.fixture()
def superadmin_headers(db) -> dict:
    from app.core.security import get_password_hash
    from app.models.usuario import AuthProvider, RolUsuario, Usuario

    from tests.conftest import TEST_PASSWORD, make_access_token

    user = Usuario(
        username="rrhh_superadmin",
        email="rrhh_super@test.com",
        nombre="RRHH Superadmin",
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.SUPERADMIN,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def test_endpoint_devuelve_el_documento(db, client, superadmin_headers, empleado_lun_vie):
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 11, 57, tzinfo=timezone.utc))
    _fichada(db, empleado_lun_vie, datetime(2026, 8, 3, 21, 3, tzinfo=timezone.utc))

    resp = client.get(
        ENDPOINT,
        params={"fecha_desde": LUNES.isoformat(), "fecha_hasta": LUNES.isoformat()},
        headers=superadmin_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["fecha_desde"] == LUNES.isoformat()
    dia = body["empleados"][0]["dias"][0]
    assert (dia["entrada"], dia["salida"], dia["horas_hhmm"]) == ("08:57", "18:03", "09:06")


def test_endpoint_acepta_empleado_ids_repetido(db, client, superadmin_headers, empleado_lun_vie):
    otro = RRHHEmpleado(
        nombre="Ana",
        apellido="Álvarez",
        dni="28999888",
        legajo="0043",
        fecha_ingreso=date(2021, 1, 1),
        estado="activo",
        activo=True,
    )
    db.add(otro)
    db.flush()

    resp = client.get(
        f"{ENDPOINT}?fecha_desde={LUNES}&fecha_hasta={LUNES}&empleado_ids={empleado_lun_vie.id}&empleado_ids={otro.id}",
        headers=superadmin_headers,
    )

    assert resp.status_code == 200
    assert {e["empleado_id"] for e in resp.json()["empleados"]} == {empleado_lun_vie.id, otro.id}


def test_endpoint_rechaza_rango_mayor_al_tope(client, superadmin_headers):
    resp = client.get(
        ENDPOINT,
        params={"fecha_desde": "2026-01-01", "fecha_hasta": "2026-06-01"},
        headers=superadmin_headers,
    )

    assert resp.status_code == 400
    # `http_exception_handler` normaliza los detail string al envelope estándar.
    assert "62" in resp.json()["error"]["message"]


def test_endpoint_exige_permiso_rrhh_ver(client, auth_headers):
    resp = client.get(
        ENDPOINT,
        params={"fecha_desde": LUNES.isoformat(), "fecha_hasta": LUNES.isoformat()},
        headers=auth_headers,
    )

    assert resp.status_code == 403
    assert "rrhh.ver" in resp.json()["error"]["message"]


def test_endpoint_exige_autenticacion(client):
    resp = client.get(
        ENDPOINT,
        params={"fecha_desde": LUNES.isoformat(), "fecha_hasta": LUNES.isoformat()},
    )

    assert resp.status_code in (401, 403)
