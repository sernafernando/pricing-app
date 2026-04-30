"""
Service layer del módulo Horas Extras (HE) — Batch 2.

Responsabilidades:
- Detección automática de bloques HE a partir de fichadas + turnos.
- Workflow de transiciones de estado (aprobar / rechazar / reabrir / liquidar).
- Manejo de anomalías (fichadas faltantes / descartar día).
- Hooks idempotentes ante modificación de fichadas y cambios de turno.
- Auditoría append-only en `rrhh_horas_extras_historial`.
- Purga de alertas leídas viejas.

Convenciones (design §7):
- Idempotencia: bloques en estado congelado (aprobada / rechazada / liquidada)
  NUNCA se sobrescriben por el cron. Cualquier divergencia genera alerta.
- `_log_historial` debe llamarse ANTES del commit (atomicidad).
- `error_fichadas` es estado terminal del cron — requiere intervención humana.
- Permisos: el service NO los valida; eso es responsabilidad del router.
- Todas las consultas asumen `RRHHFichada.timestamp` con timezone (TZ ART implícita
  en cómo se guardó el dato; reutilizamos el patrón de `rrhh_reportes_service`).

Notas de divergencia con el design:
- El design usa enum string `error_tipo` en `_validar_fichadas_dia`. La impl usa el
  enum real `ErrorTipoHE` ya importado desde `models.rrhh_horas_extras`.
- `_clasificar_tipo_dia` del design devolvía `(tipo, minutos, pct)` — la impl usa el
  contrato indicado por el orquestador: `(TipoDiaHE, hora_inicio, hora_fin)` para
  permitir que `_calcular_he_dia` haga el split por intervalos antes de calcular
  minutos por tramo (más limpio y testeable).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Date, cast, func, or_
from sqlalchemy.orm import Session

from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
from app.models.rrhh_horas_extras import (
    TIPO_ALERTA_FICHADA_ELIMINADA,
    TIPO_ALERTA_FICHADA_MODIFICADA,
    TIPO_ALERTA_LIQUIDACION_AFECTADA_POR_CAMBIO_TURNO,
    ErrorTipoHE,
    EstadoHE,
    GeneradaPorHE,
    RRHHHorasExtras,
    RRHHHorasExtrasAlerta,
    RRHHHorasExtrasConfig,
    RRHHHorasExtrasHistorial,
    TipoDiaHE,
)
from app.models.rrhh_presentismo import RRHHPresentismoDiario
from app.services.rrhh_hikvision_client import ART_TZ

logger = logging.getLogger(__name__)


# Estados que NO deben ser tocados por el cron / recálculo automático.
# `error_fichadas` requiere intervención humana — el cron tampoco lo recalcula
# silenciosamente porque ya hubo un fallo y queremos preservar evidencia.
_ESTADOS_CONGELADOS = (
    EstadoHE.APROBADA.value,
    EstadoHE.RECHAZADA.value,
    EstadoHE.LIQUIDADA.value,
    EstadoHE.ERROR_FICHADAS.value,
)

# Estados editables por el cron (se borran y se recalculan).
_ESTADOS_EDITABLES = (
    EstadoHE.PENDIENTE_ASIGNACION_TURNO.value,
    EstadoHE.DETECTADA.value,
)

# Presentismos que descartan HE del día.
_PRESENTISMOS_BLOQUEAN_HE = ("vacaciones", "art", "licencia", "feriado")

# Acciones documentadas en historial (design §2.3).
_ACCION_DETECTADA = "detectada"
_ACCION_RECALCULADA = "recalculada"
_ACCION_APROBADA = "aprobada"
_ACCION_RECHAZADA = "rechazada"
_ACCION_REABIERTA = "reabierta"
_ACCION_LIQUIDADA = "liquidada"
_ACCION_COMPLETADA_FICHADA = "completada_fichada"
_ACCION_DESCARTADA = "descartada"
_ACCION_FICHADA_MODIFICADA = "fichada_modificada_post_aprobacion"
_ACCION_RECALCULO_CAMBIO_TURNO = "recalculo_por_cambio_turno"


class HorasExtrasService:
    """
    Lógica de negocio del módulo HE.

    Uso típico:
        service = HorasExtrasService(db)
        service.detectar_he_periodo(date(2026, 4, 29), date(2026, 4, 29))
        service.aprobar_bloque(he_id=42, usuario_id=7)
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._config_cache: RRHHHorasExtrasConfig | None = None

    # ─── Config helper ──────────────────────────────────────────────────

    def _get_config(self) -> RRHHHorasExtrasConfig:
        """Carga + cachea singleton id=1. Lanza 500 si no existe."""
        if self._config_cache is not None:
            return self._config_cache
        cfg = self.db.query(RRHHHorasExtrasConfig).filter(RRHHHorasExtrasConfig.id == 1).first()
        if cfg is None:
            logger.error("❌ RRHHHorasExtrasConfig singleton (id=1) no existe")
            raise HTTPException(
                status_code=500,
                detail="Configuración de horas extras no inicializada (singleton id=1 ausente)",
            )
        self._config_cache = cfg
        return cfg

    def _porcentaje_para_tipo_dia(self, tipo_dia: TipoDiaHE, config: RRHHHorasExtrasConfig) -> Decimal:
        """Mapea tipo_dia → porcentaje_recargo desde config."""
        if tipo_dia == TipoDiaHE.HABIL_50:
            return Decimal(config.porcentaje_dia_habil)
        if tipo_dia == TipoDiaHE.SABADO_100:
            return Decimal(config.porcentaje_sabado_pm)
        if tipo_dia == TipoDiaHE.DOMINGO_100:
            return Decimal(config.porcentaje_domingo)
        if tipo_dia == TipoDiaHE.FERIADO_100:
            return Decimal(config.porcentaje_feriado)
        # MANUAL — no hay default, se setea explícitamente.
        return Decimal("0.00")

    # ─── T-2.1 — Clasificación de tipo de día ───────────────────────────

    def _clasificar_tipo_dia(self, fecha: date, hora_corte_sabado: time) -> list[tuple[TipoDiaHE, time, time]]:
        """
        Clasifica el día en tramos (tipo_dia, hora_inicio, hora_fin) cubriendo [00:00, 24:00).

        Reglas:
          - Si está en `rrhh_horarios_excepciones` con es_laborable=False → feriado_100 (todo el día).
          - Domingo (weekday() == 6) → domingo_100 (todo el día).
          - Sábado (weekday() == 5) → split habil_50 [00:00, corte) + sabado_100 [corte, 24:00).
          - Else (Lun-Vie) → habil_50 (todo el día).

        El `hora_corte_sabado` viene del singleton config (default 13:00).

        Returns:
            Lista de tuplas (tipo_dia, hora_inicio, hora_fin). Siempre cubre el día completo.
            En sábado son 2 tuplas; en cualquier otro caso, 1 tupla.

        Notas:
        - El "fin" 24:00 no es expresable como `time` válido (max es 23:59:59.999999),
          por lo que usamos `time(23, 59, 59, 999999)` como sentinel y los callers
          tratan a "hasta fin del día" comparando `< 24:00` lógicamente.
        """
        FIN_DIA = time(23, 59, 59, 999999)
        INICIO_DIA = time(0, 0, 0)

        # 1. Excepción del calendario (feriado u otro día especial no laborable).
        excepcion = self.db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.fecha == fecha).first()
        if excepcion is not None and not excepcion.es_laborable:
            return [(TipoDiaHE.FERIADO_100, INICIO_DIA, FIN_DIA)]

        weekday = fecha.weekday()  # 0=Lunes ... 6=Domingo

        # 2. Domingo.
        if weekday == 6:
            return [(TipoDiaHE.DOMINGO_100, INICIO_DIA, FIN_DIA)]

        # 3. Sábado: split por corte.
        if weekday == 5:
            # Si por alguna config bizarra el corte es 00:00 → todo es sabado_100.
            if hora_corte_sabado <= INICIO_DIA:
                return [(TipoDiaHE.SABADO_100, INICIO_DIA, FIN_DIA)]
            # Si corte >= 24:00 (no debería pasar) → todo habil_50.
            return [
                (TipoDiaHE.HABIL_50, INICIO_DIA, hora_corte_sabado),
                (TipoDiaHE.SABADO_100, hora_corte_sabado, FIN_DIA),
            ]

        # 4. Lunes-Viernes.
        return [(TipoDiaHE.HABIL_50, INICIO_DIA, FIN_DIA)]

    # ─── T-2.2 — Validación de fichadas del día ─────────────────────────

    def _validar_fichadas_dia(self, fichadas: list[RRHHFichada]) -> tuple[bool, ErrorTipoHE | None]:
        """
        Valida que las fichadas del día formen pares entrada/salida coherentes.

        Asume `fichadas` ordenadas por timestamp ascendente.

        Reglas:
          - Vacío → (False, None) — no hay HE para ese día (no error tampoco).
          - Cantidad impar → fichadas_desbalanceadas.
          - Primera es 'salida' → sin_fichada_entrada.
          - Última es 'entrada' → sin_fichada_salida.
          - Dos entradas (o dos salidas) consecutivas → solapamiento.
          - Alternancia entrada→salida→entrada→salida → válido.

        Returns:
            (válido, error_tipo). Si válido, error_tipo es None.
        """
        if not fichadas:
            return False, None

        if len(fichadas) % 2 != 0:
            return False, ErrorTipoHE.FICHADAS_DESBALANCEADAS

        if fichadas[0].tipo != "entrada":
            return False, ErrorTipoHE.SIN_FICHADA_ENTRADA

        if fichadas[-1].tipo != "salida":
            return False, ErrorTipoHE.SIN_FICHADA_SALIDA

        # Alternancia estricta.
        esperado = "entrada"
        for f in fichadas:
            if f.tipo != esperado:
                # Dos entradas o dos salidas seguidas.
                return False, ErrorTipoHE.SOLAPAMIENTO
            esperado = "salida" if esperado == "entrada" else "entrada"

        return True, None

    # ─── T-2.3 — Cálculo de HE para un día ──────────────────────────────

    def _fichadas_del_dia(self, empleado_id: int, fecha: date) -> list[RRHHFichada]:
        """
        Carga las fichadas del empleado en `fecha`.

        Reutiliza el patrón de `rrhh_reportes_service.horas_trabajadas` —
        cast(timestamp, Date) == fecha (sin TZ explícito; matching por fecha
        local del servidor).
        """
        return (
            self.db.query(RRHHFichada)
            .filter(
                RRHHFichada.empleado_id == empleado_id,
                cast(RRHHFichada.timestamp, Date) == fecha,
            )
            .order_by(RRHHFichada.timestamp.asc())
            .all()
        )

    def _minutos_trabajados(self, fichadas: list[RRHHFichada]) -> int:
        """
        Suma minutos trabajados emparejando entrada/salida secuencialmente.

        Asume fichadas ordenadas y validadas (pares balanceados).
        """
        total = 0
        # Itera en pares (entrada, salida).
        for i in range(0, len(fichadas), 2):
            if i + 1 >= len(fichadas):
                break
            entrada = fichadas[i]
            salida = fichadas[i + 1]
            delta = salida.timestamp - entrada.timestamp
            total += max(int(delta.total_seconds() // 60), 0)
        return total

    def _turno_esperado_minutos(self, empleado_id: int, fecha: date) -> tuple[int, bool]:
        """
        Calcula los minutos esperados según los turnos asignados que cubren
        este día de la semana.

        Maneja el riesgo §12 del design (M:N solapamiento): deduplica por
        `horario_config_id` para no contar el mismo turno dos veces si una
        asignación duplicada existe.

        Returns:
            (minutos_esperados, tiene_alguna_asignacion). El segundo flag
            distingue "empleado sin turno asignado" (→ pendiente_asignacion_turno)
            de "empleado con turnos pero ninguno cubre este weekday" (→ HE puro).
        """
        # weekday(): 0=Lun ... 6=Dom; en RRHHHorarioConfig.dias_semana 1=Lun ... 7=Dom.
        weekday_str = str(fecha.weekday() + 1)

        # ¿El empleado tiene CUALQUIER asignación de turno? (independiente del día).
        tiene_alguna = (
            self.db.query(RRHHEmpleadoHorario).filter(RRHHEmpleadoHorario.empleado_id == empleado_id).first()
            is not None
        )

        if not tiene_alguna:
            return 0, False

        # Turnos del empleado que cubren este weekday y están activos.
        turnos = (
            self.db.query(RRHHHorarioConfig)
            .join(
                RRHHEmpleadoHorario,
                RRHHEmpleadoHorario.horario_config_id == RRHHHorarioConfig.id,
            )
            .filter(
                RRHHEmpleadoHorario.empleado_id == empleado_id,
                RRHHHorarioConfig.activo.is_(True),
            )
            .all()
        )

        # Dedup por id (riesgo §12).
        vistos: set[int] = set()
        minutos = 0
        for t in turnos:
            if t.id in vistos:
                continue
            vistos.add(t.id)
            # Filtrar por weekday — el campo `dias_semana` es CSV "1,2,3,4,5".
            dias = [d.strip() for d in (t.dias_semana or "").split(",") if d.strip()]
            if weekday_str not in dias:
                continue
            entrada_min = t.hora_entrada.hour * 60 + t.hora_entrada.minute
            salida_min = t.hora_salida.hour * 60 + t.hora_salida.minute
            minutos += max(salida_min - entrada_min, 0)

        return minutos, True

    def _hay_presentismo_bloqueante(self, empleado_id: int, fecha: date) -> bool:
        """True si presentismo es vacaciones/art/licencia/feriado."""
        row = (
            self.db.query(RRHHPresentismoDiario)
            .filter(
                RRHHPresentismoDiario.empleado_id == empleado_id,
                RRHHPresentismoDiario.fecha == fecha,
            )
            .first()
        )
        if row is None:
            return False
        return row.estado in _PRESENTISMOS_BLOQUEAN_HE

    def _split_extras_por_tramo(
        self,
        fichadas_pares: list[tuple[datetime, datetime]],
        tramos_dia: list[tuple[TipoDiaHE, time, time]],
        extras_minutos_total: int,
        trabajado_minutos_total: int,
    ) -> dict[TipoDiaHE, dict[str, int]]:
        """
        Distribuye `extras_minutos_total` entre los tramos del día en proporción
        a los minutos trabajados que caen en cada tramo.

        Para casos simples (1 tramo) → todo va al único tipo_dia.
        Para sábado (2 tramos) → distribuye según cuánto trabajó antes/después
        del corte.

        Returns:
            { TipoDiaHE: { 'extras': int, 'trabajado': int } } — solo tramos con extras > 0.
        """
        # Calculamos minutos trabajados por tramo.
        por_tramo: dict[TipoDiaHE, int] = {tipo: 0 for tipo, _, _ in tramos_dia}

        for entrada_dt, salida_dt in fichadas_pares:
            for tipo, hi, hf in tramos_dia:
                # Convertimos hi/hf del tramo a datetime del mismo día que la fichada.
                base = entrada_dt.date()
                tramo_inicio = datetime.combine(base, hi, tzinfo=entrada_dt.tzinfo)
                # Si hf es FIN_DIA sentinel → fin real es 24:00 = inicio del día siguiente.
                if hf == time(23, 59, 59, 999999):
                    tramo_fin = datetime.combine(base + timedelta(days=1), time(0, 0), tzinfo=entrada_dt.tzinfo)
                else:
                    tramo_fin = datetime.combine(base, hf, tzinfo=entrada_dt.tzinfo)
                # Intersección [entrada_dt, salida_dt] ∩ [tramo_inicio, tramo_fin).
                inter_inicio = max(entrada_dt, tramo_inicio)
                inter_fin = min(salida_dt, tramo_fin)
                if inter_fin > inter_inicio:
                    por_tramo[tipo] += int((inter_fin - inter_inicio).total_seconds() // 60)

        # Distribuir extras_minutos_total proporcional a trabajado.
        if trabajado_minutos_total <= 0:
            return {}

        resultado: dict[TipoDiaHE, dict[str, int]] = {}
        asignado = 0
        # Lista de tipos con minutos>0, ordenada por enum.value para determinismo.
        tipos_con_trabajo = [t for t, m in por_tramo.items() if m > 0]
        for idx, tipo in enumerate(tipos_con_trabajo):
            trabajado_t = por_tramo[tipo]
            if idx == len(tipos_con_trabajo) - 1:
                # Último: absorbe el resto para evitar pérdidas por redondeo.
                extras_t = extras_minutos_total - asignado
            else:
                extras_t = int(round(extras_minutos_total * trabajado_t / trabajado_minutos_total))
            asignado += extras_t
            if extras_t > 0:
                resultado[tipo] = {"extras": extras_t, "trabajado": trabajado_t}
        return resultado

    def _calcular_he_dia(
        self, empleado: RRHHEmpleado, fecha: date, config: RRHHHorasExtrasConfig
    ) -> list[dict[str, Any]]:
        """
        Calcula los bloques HE del empleado para un día.

        Sigue los 8 steps documentados en design §7:
          1. Cargar fichadas del empleado en `fecha`.
          2. Si presentismo del día es vacaciones/art/licencia/feriado → return [].
          3. Si no hay fichadas → return [] (no HE).
          4. Validar fichadas. Si inválido → return UN bloque error_fichadas.
          5. Calcular minutos trabajados.
          6. Obtener turnos esperados del día.
             - Sin asignación alguna → return UN bloque pendiente_asignacion_turno.
          7. Comparar trabajado vs esperado contra tolerancia.
          8. Si hay extras → clasificar tipo_dia (posible split sábado) y armar dicts.

        Returns:
            Lista de "bloque dicts" listos para persistir (no insertados aquí).
            Cada dict contiene: empleado_id, fecha, fichada_entrada_id, fichada_salida_id,
            turno_esperado_minutos, trabajado_minutos, extras_minutos, tipo_dia,
            porcentaje_recargo, estado, generada_por, observaciones, error_tipo.

        Idempotencia: este método NO consulta ni borra bloques existentes — eso lo
        hace `detectar_he_periodo`. Es un cálculo puro modulo sus queries.
        """
        # 1. Fichadas del día.
        fichadas = self._fichadas_del_dia(empleado.id, fecha)

        # 2. Presentismo bloqueante.
        if self._hay_presentismo_bloqueante(empleado.id, fecha):
            return []

        # 3. Sin fichadas → no HE.
        if not fichadas:
            return []

        # 4. Validar.
        valido, error_tipo = self._validar_fichadas_dia(fichadas)
        if not valido and error_tipo is not None:
            # Bloque único de error.
            return [
                {
                    "empleado_id": empleado.id,
                    "fecha": fecha,
                    "fichada_entrada_id": fichadas[0].id if fichadas else None,
                    "fichada_salida_id": fichadas[-1].id if fichadas else None,
                    "turno_esperado_minutos": 0,
                    "trabajado_minutos": None,
                    "extras_minutos": None,
                    "tipo_dia": TipoDiaHE.HABIL_50.value,  # placeholder; estado=error
                    "porcentaje_recargo": Decimal("0.00"),
                    "estado": EstadoHE.ERROR_FICHADAS.value,
                    "error_tipo": error_tipo.value,
                    "generada_por": GeneradaPorHE.SISTEMA.value,
                    "observaciones": f"Fichadas del día inválidas: {error_tipo.value}",
                }
            ]

        # 5. Minutos trabajados.
        trabajado_min = self._minutos_trabajados(fichadas)

        # 6. Turno esperado.
        turno_esperado_min, tiene_asignacion = self._turno_esperado_minutos(empleado.id, fecha)

        if not tiene_asignacion:
            return [
                {
                    "empleado_id": empleado.id,
                    "fecha": fecha,
                    "fichada_entrada_id": fichadas[0].id,
                    "fichada_salida_id": fichadas[-1].id,
                    "turno_esperado_minutos": 0,
                    "trabajado_minutos": trabajado_min,
                    "extras_minutos": None,
                    "tipo_dia": TipoDiaHE.HABIL_50.value,
                    "porcentaje_recargo": Decimal("0.00"),
                    "estado": EstadoHE.PENDIENTE_ASIGNACION_TURNO.value,
                    "error_tipo": None,
                    "generada_por": GeneradaPorHE.SISTEMA.value,
                    "observaciones": (
                        "Empleado sin turno asignado. Asignar turno y reprocesar para detectar HE reales."
                    ),
                }
            ]

        # 7. Comparar contra tolerancia.
        # Spec: HE menor O IGUAL a tolerancia NO se registra.
        extras_brutos = max(0, trabajado_min - turno_esperado_min)
        if extras_brutos <= config.tolerancia_extras_minutos:
            return []

        # 8. Clasificar tipo_dia y dividir si corresponde.
        tramos = self._clasificar_tipo_dia(fecha, config.hora_corte_sabado)

        # Armar pares (entrada_dt, salida_dt) para el split por tramo.
        pares: list[tuple[datetime, datetime]] = []
        for i in range(0, len(fichadas), 2):
            if i + 1 < len(fichadas):
                pares.append((fichadas[i].timestamp, fichadas[i + 1].timestamp))

        if len(tramos) == 1:
            # Caso simple: todo el extra va al único tipo_dia.
            tipo, _hi, _hf = tramos[0]
            return [
                {
                    "empleado_id": empleado.id,
                    "fecha": fecha,
                    "fichada_entrada_id": fichadas[0].id,
                    "fichada_salida_id": fichadas[-1].id,
                    "turno_esperado_minutos": turno_esperado_min,
                    "trabajado_minutos": trabajado_min,
                    "extras_minutos": extras_brutos,
                    "tipo_dia": tipo.value,
                    "porcentaje_recargo": self._porcentaje_para_tipo_dia(tipo, config),
                    "estado": EstadoHE.DETECTADA.value,
                    "error_tipo": None,
                    "generada_por": GeneradaPorHE.SISTEMA.value,
                    "observaciones": None,
                }
            ]

        # Caso sábado split.
        distribucion = self._split_extras_por_tramo(pares, tramos, extras_brutos, trabajado_min)
        bloques: list[dict[str, Any]] = []
        for tipo, datos in distribucion.items():
            bloques.append(
                {
                    "empleado_id": empleado.id,
                    "fecha": fecha,
                    "fichada_entrada_id": fichadas[0].id,
                    "fichada_salida_id": fichadas[-1].id,
                    "turno_esperado_minutos": turno_esperado_min,
                    "trabajado_minutos": datos["trabajado"],
                    "extras_minutos": datos["extras"],
                    "tipo_dia": tipo.value,
                    "porcentaje_recargo": self._porcentaje_para_tipo_dia(tipo, config),
                    "estado": EstadoHE.DETECTADA.value,
                    "error_tipo": None,
                    "generada_por": GeneradaPorHE.SISTEMA.value,
                    "observaciones": None,
                }
            )
        return bloques

    # ─── T-2.5 — Audit trail append-only ────────────────────────────────

    def _snapshot_bloque(self, he: RRHHHorasExtras) -> dict[str, Any]:
        """Snapshot serializable a JSONB con los campos materiales del bloque."""
        return {
            "extras_minutos": he.extras_minutos,
            "trabajado_minutos": he.trabajado_minutos,
            "turno_esperado_minutos": he.turno_esperado_minutos,
            "tipo_dia": he.tipo_dia,
            "porcentaje_recargo": (str(he.porcentaje_recargo) if he.porcentaje_recargo is not None else None),
            "estado": he.estado,
            "observaciones": he.observaciones,
            "fichada_entrada_id": he.fichada_entrada_id,
            "fichada_salida_id": he.fichada_salida_id,
        }

    def _log_historial(
        self,
        he: RRHHHorasExtras,
        accion: str,
        estado_anterior: str | None,
        estado_nuevo: str,
        usuario_id: int | None = None,
        motivo: str | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> RRHHHorasExtrasHistorial:
        """
        Append-only insert en `rrhh_horas_extras_historial`.

        DEBE llamarse ANTES del commit del cambio para garantizar atomicidad.
        El caller controla el commit.
        """
        if snapshot is None:
            snapshot = self._snapshot_bloque(he)
        row = RRHHHorasExtrasHistorial(
            he_id=he.id,
            accion=accion,
            estado_anterior=estado_anterior,
            estado_nuevo=estado_nuevo,
            usuario_id=usuario_id,
            motivo=motivo,
            snapshot=snapshot,
        )
        self.db.add(row)
        return row

    # ─── T-2.4 — Detección por período ──────────────────────────────────

    def detectar_he_periodo(
        self,
        fecha_desde: date,
        fecha_hasta: date,
        empleado_ids: list[int] | None = None,
    ) -> dict[str, int]:
        """
        Detecta HE para todos los empleados activos en el rango [desde, hasta].

        Idempotente:
          - Bloques en estado congelado (aprobada/rechazada/liquidada/error_fichadas)
            NO se sobrescriben — se conservan.
          - Bloques en estado editable (detectada/pendiente_asignacion_turno) se
            ELIMINAN antes de recalcular para mantener el resultado actualizado.

        Args:
            fecha_desde: inclusive.
            fecha_hasta: inclusive.
            empleado_ids: si provisto, restringe el cálculo a esos IDs.

        Returns:
            { procesados, creados, actualizados, alertas, errores, pendientes_turno }
        """
        if fecha_hasta < fecha_desde:
            raise HTTPException(
                status_code=422,
                detail=f"fecha_hasta ({fecha_hasta}) debe ser >= fecha_desde ({fecha_desde})",
            )

        config = self._get_config()

        emp_query = self.db.query(RRHHEmpleado).filter(
            RRHHEmpleado.activo.is_(True),
            RRHHEmpleado.estado == "activo",
        )
        if empleado_ids is not None:
            emp_query = emp_query.filter(RRHHEmpleado.id.in_(empleado_ids))

        empleados = emp_query.all()

        procesados = 0
        creados = 0
        actualizados = 0
        alertas = 0
        errores = 0
        pendientes_turno = 0

        # Iterar fechas.
        dias: list[date] = []
        d = fecha_desde
        while d <= fecha_hasta:
            dias.append(d)
            d = d + timedelta(days=1)

        for emp in empleados:
            for fecha in dias:
                procesados += 1
                try:
                    # Borrar bloques editables existentes (recálculo).
                    existentes_editables = (
                        self.db.query(RRHHHorasExtras)
                        .filter(
                            RRHHHorasExtras.empleado_id == emp.id,
                            RRHHHorasExtras.fecha == fecha,
                            RRHHHorasExtras.estado.in_(_ESTADOS_EDITABLES),
                        )
                        .all()
                    )
                    for old in existentes_editables:
                        self.db.delete(old)
                        actualizados += 1

                    # Si quedan bloques congelados para (emp, fecha), no recalculamos
                    # nada nuevo (ya fueron procesados). El service confía en el hook
                    # `notificar_fichada_modificada` para detectar divergencias.
                    tiene_congelados = (
                        self.db.query(RRHHHorasExtras.id)
                        .filter(
                            RRHHHorasExtras.empleado_id == emp.id,
                            RRHHHorasExtras.fecha == fecha,
                            RRHHHorasExtras.estado.in_(_ESTADOS_CONGELADOS),
                        )
                        .first()
                        is not None
                    )
                    if tiene_congelados:
                        continue

                    # Calcular nuevos bloques.
                    nuevos = self._calcular_he_dia(emp, fecha, config)
                    for data in nuevos:
                        bloque = RRHHHorasExtras(**data)
                        self.db.add(bloque)
                        # flush para obtener id antes del historial.
                        self.db.flush()
                        creados += 1
                        if bloque.estado == EstadoHE.PENDIENTE_ASIGNACION_TURNO.value:
                            pendientes_turno += 1
                        if bloque.estado == EstadoHE.ERROR_FICHADAS.value:
                            errores += 1
                        self._log_historial(
                            bloque,
                            accion=_ACCION_DETECTADA,
                            estado_anterior=None,
                            estado_nuevo=bloque.estado,
                            usuario_id=None,
                            motivo="Detección automática (cron / batch)",
                        )
                except HTTPException:
                    raise
                except Exception as exc:  # noqa: BLE001 — boundary del loop
                    errores += 1
                    logger.error(
                        "❌ Error detectando HE empleado=%s fecha=%s: %s",
                        emp.id,
                        fecha,
                        exc,
                        exc_info=True,
                    )

        self.db.commit()

        logger.info(
            "✅ detectar_he_periodo procesados=%d creados=%d actualizados=%d errores=%d pendientes_turno=%d alertas=%d",
            procesados,
            creados,
            actualizados,
            errores,
            pendientes_turno,
            alertas,
        )

        return {
            "procesados": procesados,
            "creados": creados,
            "actualizados": actualizados,
            "alertas": alertas,
            "errores": errores,
            "pendientes_turno": pendientes_turno,
        }

    # ─── T-2.6 — Workflow ───────────────────────────────────────────────

    def _get_bloque_or_404(self, he_id: int) -> RRHHHorasExtras:
        bloque = self.db.query(RRHHHorasExtras).filter(RRHHHorasExtras.id == he_id).first()
        if bloque is None:
            raise HTTPException(status_code=404, detail=f"Bloque HE {he_id} no encontrado")
        return bloque

    def aprobar_bloque(
        self,
        he_id: int,
        usuario_id: int,
        porcentaje_override: Decimal | None = None,
        observaciones: str | None = None,
    ) -> RRHHHorasExtras:
        """
        Transición `detectada → aprobada`.

        - Lanza 422 si el estado actual no es `detectada`.
        - `porcentaje_override`: si presente, marca `tipo_dia='manual'` y reemplaza
          el porcentaje (auditado en historial).
        """
        bloque = self._get_bloque_or_404(he_id)
        if bloque.estado != EstadoHE.DETECTADA.value:
            raise HTTPException(
                status_code=422,
                detail=(f"Bloque {he_id} en estado '{bloque.estado}' no puede aprobarse (requiere estado 'detectada')"),
            )

        snapshot_anterior = self._snapshot_bloque(bloque)
        estado_anterior = bloque.estado

        bloque.estado = EstadoHE.APROBADA.value
        bloque.aprobado_por_id = usuario_id
        bloque.aprobado_at = datetime.now(ART_TZ)
        if porcentaje_override is not None:
            bloque.porcentaje_recargo = porcentaje_override
            bloque.tipo_dia = TipoDiaHE.MANUAL.value
        if observaciones is not None:
            bloque.observaciones = observaciones

        self._log_historial(
            bloque,
            accion=_ACCION_APROBADA,
            estado_anterior=estado_anterior,
            estado_nuevo=bloque.estado,
            usuario_id=usuario_id,
            motivo=observaciones,
            snapshot=snapshot_anterior,
        )
        self.db.commit()
        self.db.refresh(bloque)
        logger.info("✅ Bloque HE %d aprobado por usuario=%d", he_id, usuario_id)
        return bloque

    def rechazar_bloque(self, he_id: int, usuario_id: int, motivo: str) -> RRHHHorasExtras:
        """
        Transición `detectada/aprobada/error_fichadas → rechazada`.

        - `motivo` no puede ser vacío (length >= 3).
        """
        if motivo is None or len(motivo.strip()) < 3:
            raise HTTPException(
                status_code=422,
                detail="El motivo de rechazo es obligatorio (mínimo 3 caracteres)",
            )

        bloque = self._get_bloque_or_404(he_id)
        estados_validos = (
            EstadoHE.DETECTADA.value,
            EstadoHE.APROBADA.value,
            EstadoHE.ERROR_FICHADAS.value,
        )
        if bloque.estado not in estados_validos:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bloque {he_id} en estado '{bloque.estado}' no puede rechazarse "
                    f"(requiere uno de {estados_validos})"
                ),
            )

        snapshot_anterior = self._snapshot_bloque(bloque)
        estado_anterior = bloque.estado

        bloque.estado = EstadoHE.RECHAZADA.value
        bloque.motivo_rechazo = motivo
        bloque.aprobado_por_id = usuario_id  # quien tomó la acción
        bloque.aprobado_at = datetime.now(ART_TZ)

        self._log_historial(
            bloque,
            accion=_ACCION_RECHAZADA,
            estado_anterior=estado_anterior,
            estado_nuevo=bloque.estado,
            usuario_id=usuario_id,
            motivo=motivo,
            snapshot=snapshot_anterior,
        )
        self.db.commit()
        self.db.refresh(bloque)
        logger.info("✅ Bloque HE %d rechazado por usuario=%d", he_id, usuario_id)
        return bloque

    def reabrir_bloque(self, he_id: int, usuario_id: int, motivo: str) -> RRHHHorasExtras:
        """
        Reapertura con auditoría:
          - aprobada → detectada (limpia aprobado_*).
          - liquidada → aprobada (limpia liquidacion_* — requiere permiso `liquidar`
            chequeado por el router).
          - rechazada → detectada.

        Setea `reabierto_por_id`, `reabierto_at`, `motivo_reapertura`.
        """
        if motivo is None or len(motivo.strip()) < 3:
            raise HTTPException(
                status_code=422,
                detail="El motivo de reapertura es obligatorio (mínimo 3 caracteres)",
            )

        bloque = self._get_bloque_or_404(he_id)
        estado_anterior = bloque.estado
        snapshot_anterior = self._snapshot_bloque(bloque)

        if bloque.estado == EstadoHE.APROBADA.value:
            bloque.estado = EstadoHE.DETECTADA.value
            bloque.aprobado_por_id = None
            bloque.aprobado_at = None
            bloque.motivo_rechazo = None
        elif bloque.estado == EstadoHE.RECHAZADA.value:
            bloque.estado = EstadoHE.DETECTADA.value
            bloque.aprobado_por_id = None
            bloque.aprobado_at = None
            bloque.motivo_rechazo = None
        elif bloque.estado == EstadoHE.LIQUIDADA.value:
            # Reapertura post-liquidación → vuelve a aprobada.
            bloque.estado = EstadoHE.APROBADA.value
            bloque.liquidacion_periodo = None
            bloque.liquidado_por_id = None
            bloque.liquidado_at = None
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bloque {he_id} en estado '{bloque.estado}' no puede reabrirse "
                    "(requiere aprobada / rechazada / liquidada)"
                ),
            )

        bloque.reabierto_por_id = usuario_id
        bloque.reabierto_at = datetime.now(ART_TZ)
        bloque.motivo_reapertura = motivo

        self._log_historial(
            bloque,
            accion=_ACCION_REABIERTA,
            estado_anterior=estado_anterior,
            estado_nuevo=bloque.estado,
            usuario_id=usuario_id,
            motivo=motivo,
            snapshot=snapshot_anterior,
        )
        self.db.commit()
        self.db.refresh(bloque)
        logger.info(
            "✅ Bloque HE %d reabierto (%s → %s) por usuario=%d",
            he_id,
            estado_anterior,
            bloque.estado,
            usuario_id,
        )
        return bloque

    # ─── T-2.7 — Anomalías ──────────────────────────────────────────────

    def completar_fichada_faltante(
        self,
        he_id: int,
        usuario_id: int,
        timestamp: datetime,
        tipo: str,
        motivo: str,
    ) -> RRHHHorasExtras:
        """
        Solo desde `error_fichadas`:
          1. Crea fichada manual (origen='manual', motivo_manual=motivo).
          2. Recalcula el día → si las nuevas fichadas son válidas, el bloque pasa a
             `detectada`. Si nuevas HE < tolerancia, el bloque puede desaparecer
             (en cuyo caso devolvemos el bloque original con estado actualizado).
        """
        if motivo is None or len(motivo.strip()) < 3:
            raise HTTPException(
                status_code=422,
                detail="El motivo de la fichada manual es obligatorio (mínimo 3 caracteres)",
            )
        if tipo not in ("entrada", "salida"):
            raise HTTPException(
                status_code=422,
                detail=f"tipo inválido '{tipo}' (esperado 'entrada' o 'salida')",
            )

        bloque = self._get_bloque_or_404(he_id)
        if bloque.estado != EstadoHE.ERROR_FICHADAS.value:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bloque {he_id} en estado '{bloque.estado}' no admite "
                    "completar fichada (requiere 'error_fichadas')"
                ),
            )

        empleado_id = bloque.empleado_id
        fecha = bloque.fecha
        config = self._get_config()

        # 1. Crear fichada manual.
        fichada = RRHHFichada(
            empleado_id=empleado_id,
            timestamp=timestamp,
            tipo=tipo,
            origen="manual",
            registrado_por_id=usuario_id,
            motivo_manual=motivo,
        )
        self.db.add(fichada)
        self.db.flush()

        # 2. Borrar bloques editables o de error del día (vamos a recalcular).
        viejos = (
            self.db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.empleado_id == empleado_id,
                RRHHHorasExtras.fecha == fecha,
                RRHHHorasExtras.estado.in_(list(_ESTADOS_EDITABLES) + [EstadoHE.ERROR_FICHADAS.value]),
            )
            .all()
        )

        # Antes de borrarlos, registrar el snapshot del bloque original con accion=completada_fichada.
        snapshot_anterior = self._snapshot_bloque(bloque)
        estado_anterior = bloque.estado

        for v in viejos:
            self.db.delete(v)
        self.db.flush()

        # 3. Empleado para recálculo.
        empleado = self.db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
        if empleado is None:
            raise HTTPException(status_code=404, detail=f"Empleado {empleado_id} no encontrado")

        nuevos = self._calcular_he_dia(empleado, fecha, config)
        bloque_resultado: RRHHHorasExtras | None = None
        for data in nuevos:
            nb = RRHHHorasExtras(**data)
            self.db.add(nb)
            self.db.flush()
            self._log_historial(
                nb,
                accion=_ACCION_COMPLETADA_FICHADA,
                estado_anterior=estado_anterior,
                estado_nuevo=nb.estado,
                usuario_id=usuario_id,
                motivo=f"Completada fichada manual (id={fichada.id}): {motivo}",
                snapshot=snapshot_anterior,
            )
            if bloque_resultado is None:
                bloque_resultado = nb

        self.db.commit()

        if bloque_resultado is None:
            # No hay HE tras recálculo (extras < tolerancia). Devolvemos un bloque
            # virtual representativo — pero en este caso el bloque original ya fue
            # borrado. Devolvemos un objeto detached para informar al caller.
            logger.info(
                "✅ completar_fichada_faltante he=%d: tras recálculo no hay HE (< tolerancia)",
                he_id,
            )
            # Sin bloque persistido: lanzamos 200-equivalente con info — pero el
            # contrato del método pide RRHHHorasExtras. Devolvemos el bloque con
            # los nuevos datos virtuales para que el router pueda responder.
            virtual = RRHHHorasExtras(
                id=he_id,
                empleado_id=empleado_id,
                fecha=fecha,
                turno_esperado_minutos=0,
                trabajado_minutos=0,
                extras_minutos=0,
                tipo_dia=TipoDiaHE.HABIL_50.value,
                porcentaje_recargo=Decimal("0.00"),
                estado=EstadoHE.RECHAZADA.value,
                observaciones=("Tras completar fichada, las HE quedan por debajo de la tolerancia. Bloque descartado."),
                generada_por=GeneradaPorHE.MANUAL.value,
            )
            return virtual

        logger.info(
            "✅ completar_fichada_faltante he=%d → nuevo bloque %d estado=%s",
            he_id,
            bloque_resultado.id,
            bloque_resultado.estado,
        )
        return bloque_resultado

    def descartar_dia(self, he_id: int, usuario_id: int, motivo: str) -> RRHHHorasExtras:
        """
        Solo desde `error_fichadas`: pasa a `rechazada` con motivo prefijado.
        """
        if motivo is None or len(motivo.strip()) < 3:
            raise HTTPException(
                status_code=422,
                detail="El motivo es obligatorio (mínimo 3 caracteres)",
            )

        bloque = self._get_bloque_or_404(he_id)
        if bloque.estado != EstadoHE.ERROR_FICHADAS.value:
            raise HTTPException(
                status_code=422,
                detail=(f"Bloque {he_id} en estado '{bloque.estado}' no admite descartar (requiere 'error_fichadas')"),
            )

        snapshot_anterior = self._snapshot_bloque(bloque)
        estado_anterior = bloque.estado

        bloque.estado = EstadoHE.RECHAZADA.value
        bloque.motivo_rechazo = f"[descartado] {motivo}"
        bloque.aprobado_por_id = usuario_id
        bloque.aprobado_at = datetime.now(ART_TZ)

        self._log_historial(
            bloque,
            accion=_ACCION_DESCARTADA,
            estado_anterior=estado_anterior,
            estado_nuevo=bloque.estado,
            usuario_id=usuario_id,
            motivo=motivo,
            snapshot=snapshot_anterior,
        )
        self.db.commit()
        self.db.refresh(bloque)
        logger.info("✅ Bloque HE %d descartado por usuario=%d", he_id, usuario_id)
        return bloque

    # ─── T-2.8 — Liquidación bulk ───────────────────────────────────────

    def liquidar_periodo(self, periodo: str, ids: list[int], usuario_id: int) -> dict[str, Any]:
        """
        Marca bloques `aprobada` como `liquidada` con `liquidacion_periodo=YYYYMM`.

        - `periodo`: string de 6 chars `YYYYMM` (ej "202604").
        - Errores individuales NO bloquean los demás (transacción única,
          los IDs en estado distinto se acumulan en `detalle_rechazos`).

        Returns:
            { periodo, liquidados, rechazados, detalle_rechazos: [{id, motivo}] }
        """
        if not isinstance(periodo, str) or len(periodo) != 6 or not periodo.isdigit():
            raise HTTPException(
                status_code=422,
                detail=f"periodo inválido '{periodo}' (esperado YYYYMM, 6 dígitos)",
            )
        if not ids:
            return {
                "periodo": periodo,
                "liquidados": 0,
                "rechazados": 0,
                "detalle_rechazos": [],
            }

        bloques = self.db.query(RRHHHorasExtras).filter(RRHHHorasExtras.id.in_(ids)).all()
        encontrados = {b.id for b in bloques}

        liquidados = 0
        rechazados = 0
        detalle: list[dict[str, Any]] = []

        # IDs no encontrados.
        for missing_id in set(ids) - encontrados:
            rechazados += 1
            detalle.append({"id": missing_id, "motivo": "Bloque no encontrado"})

        ahora = datetime.now(ART_TZ)
        for b in bloques:
            if b.estado != EstadoHE.APROBADA.value:
                rechazados += 1
                detalle.append(
                    {
                        "id": b.id,
                        "motivo": (f"Estado '{b.estado}' no liquidable (requiere 'aprobada')"),
                    }
                )
                continue

            snapshot_anterior = self._snapshot_bloque(b)
            estado_anterior = b.estado

            b.estado = EstadoHE.LIQUIDADA.value
            b.liquidacion_periodo = periodo
            b.liquidado_por_id = usuario_id
            b.liquidado_at = ahora

            self._log_historial(
                b,
                accion=_ACCION_LIQUIDADA,
                estado_anterior=estado_anterior,
                estado_nuevo=b.estado,
                usuario_id=usuario_id,
                motivo=f"Liquidación período {periodo}",
                snapshot=snapshot_anterior,
            )
            liquidados += 1

        self.db.commit()
        logger.info(
            "✅ liquidar_periodo periodo=%s liquidados=%d rechazados=%d",
            periodo,
            liquidados,
            rechazados,
        )
        return {
            "periodo": periodo,
            "liquidados": liquidados,
            "rechazados": rechazados,
            "detalle_rechazos": detalle,
        }

    # ─── T-2.9 — Hook fichadas modificadas ──────────────────────────────

    def _alerta_existe(self, he_id: int, tipo: str, fichada_id: int | None) -> bool:
        """Idempotencia: chequea si ya hay una alerta no leída con el mismo (he, tipo, fichada)."""
        q = self.db.query(RRHHHorasExtrasAlerta).filter(
            RRHHHorasExtrasAlerta.he_id == he_id,
            RRHHHorasExtrasAlerta.tipo == tipo,
            RRHHHorasExtrasAlerta.leida_at.is_(None),
        )
        if fichada_id is not None:
            # contexto JSONB: comparamos por contenido del key 'fichada_id'.
            q = q.filter(RRHHHorasExtrasAlerta.contexto["fichada_id"].as_integer() == fichada_id)
        return q.first() is not None

    def notificar_fichada_modificada(self, fichada_id: int, evento: str = "modificada") -> int:
        """
        Hook llamado por el event listener cuando una `RRHHFichada` es UPDATE/DELETE.

        Para cada bloque HE que referencia `fichada_entrada_id == fichada_id` o
        `fichada_salida_id == fichada_id`:
          - Si el bloque está en estado congelado (aprobada/liquidada/rechazada/
            error_fichadas) → INSERT alerta con contexto `{fichada_id, evento, ...}`
            (idempotente).
          - Si el bloque está en estado editable (detectada/pendiente_*) → no se
            hace nada acá; el cron / detección normal lo recalculará.

        Args:
            fichada_id: id de la fichada modificada.
            evento: 'modificada' | 'eliminada' | 'insertada_tardia'.

        Returns:
            Cantidad de alertas creadas (incluye 0 si todo era idempotente).
        """
        bloques = (
            self.db.query(RRHHHorasExtras)
            .filter(
                or_(
                    RRHHHorasExtras.fichada_entrada_id == fichada_id,
                    RRHHHorasExtras.fichada_salida_id == fichada_id,
                ),
                RRHHHorasExtras.estado.in_(_ESTADOS_CONGELADOS),
            )
            .all()
        )

        if evento == "eliminada":
            tipo_alerta = TIPO_ALERTA_FICHADA_ELIMINADA
        elif evento == "insertada_tardia":
            tipo_alerta = TIPO_ALERTA_FICHADA_MODIFICADA
        else:
            tipo_alerta = TIPO_ALERTA_FICHADA_MODIFICADA

        creadas = 0
        for b in bloques:
            if self._alerta_existe(b.id, tipo_alerta, fichada_id):
                continue
            severidad = "critical" if b.estado == EstadoHE.LIQUIDADA.value else "warning"
            mensaje = (
                f"Fichada #{fichada_id} ({evento}) afecta bloque HE #{b.id} "
                f"del empleado {b.empleado_id} en {b.fecha}. "
                f"Estado actual: {b.estado}."
            )
            alerta = RRHHHorasExtrasAlerta(
                he_id=b.id,
                tipo=tipo_alerta,
                severidad=severidad,
                mensaje=mensaje,
                contexto={
                    "fichada_id": fichada_id,
                    "evento": evento,
                    "empleado_id": b.empleado_id,
                    "fecha": b.fecha.isoformat() if b.fecha else None,
                    "estado_actual": b.estado,
                },
            )
            self.db.add(alerta)
            creadas += 1

            # Historial: append-only.
            self._log_historial(
                b,
                accion=_ACCION_FICHADA_MODIFICADA,
                estado_anterior=b.estado,
                estado_nuevo=b.estado,  # no cambia estado del bloque
                usuario_id=None,
                motivo=f"Fichada {fichada_id} {evento}; alerta generada",
            )

        if creadas > 0:
            self.db.commit()
            logger.info(
                "🔄 notificar_fichada_modificada fichada=%d evento=%s alertas_creadas=%d",
                fichada_id,
                evento,
                creadas,
            )
        return creadas

    # ─── T-2.10 — Recálculo por cambio de turno ─────────────────────────

    def recalcular_por_cambio_turno(self, empleado_id: int, fecha_desde_minima: date) -> dict[str, int]:
        """
        Recalcula HE de un empleado desde `fecha_desde_minima` hasta hoy.

        Aplica `cap_dias_recalculo_manual` (default 90) — si el rango excede el
        cap, se clamps a `today - cap`.

        Reglas por estado del bloque existente:
          - detectada / pendiente_asignacion_turno / error_fichadas → DELETE + recalc.
          - aprobada / rechazada → revierte a `detectada` (audita motivo) + recalc.
          - liquidada → NO se modifica; INSERT alerta `liquidacion_afectada_por_cambio_turno`
            con severidad `critical`.

        Returns:
            { procesados, recalculados, reabiertos, alertas_liquidadas, dias_clamped }
        """
        config = self._get_config()
        hoy = date.today()
        cap = config.cap_dias_recalculo_manual

        dias_clamped = 0
        fecha_minima_efectiva = fecha_desde_minima
        if (hoy - fecha_desde_minima).days > cap:
            fecha_minima_efectiva = hoy - timedelta(days=cap)
            dias_clamped = (fecha_minima_efectiva - fecha_desde_minima).days
            logger.warning(
                "⚠️ recalcular_por_cambio_turno empleado=%d: fecha_desde_minima %s clampeada a %s (cap=%d días)",
                empleado_id,
                fecha_desde_minima,
                fecha_minima_efectiva,
                cap,
            )

        empleado = self.db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
        if empleado is None:
            raise HTTPException(status_code=404, detail=f"Empleado {empleado_id} no encontrado")

        procesados = 0
        recalculados = 0
        reabiertos = 0
        alertas_liquidadas = 0

        d = fecha_minima_efectiva
        while d <= hoy:
            procesados += 1

            existentes = (
                self.db.query(RRHHHorasExtras)
                .filter(
                    RRHHHorasExtras.empleado_id == empleado_id,
                    RRHHHorasExtras.fecha == d,
                )
                .all()
            )

            for b in existentes:
                snapshot_anterior = self._snapshot_bloque(b)
                estado_anterior = b.estado

                if b.estado == EstadoHE.LIQUIDADA.value:
                    # NO modificar; alertar.
                    if not self._alerta_existe(
                        b.id,
                        TIPO_ALERTA_LIQUIDACION_AFECTADA_POR_CAMBIO_TURNO,
                        fichada_id=None,
                    ):
                        alerta = RRHHHorasExtrasAlerta(
                            he_id=b.id,
                            tipo=TIPO_ALERTA_LIQUIDACION_AFECTADA_POR_CAMBIO_TURNO,
                            severidad="critical",
                            mensaje=(
                                f"Cambio de turno detectado para empleado {empleado_id} "
                                f"afecta bloque liquidado #{b.id} ({d}). Revisar manualmente."
                            ),
                            contexto={
                                "empleado_id": empleado_id,
                                "fecha": d.isoformat(),
                                "fichada_entrada_id": b.fichada_entrada_id,
                                "fichada_salida_id": b.fichada_salida_id,
                                "snapshot_actual": snapshot_anterior,
                            },
                        )
                        self.db.add(alerta)
                        alertas_liquidadas += 1
                    continue

                if b.estado in (EstadoHE.APROBADA.value, EstadoHE.RECHAZADA.value):
                    # Revertir a detectada con auditoría.
                    b.estado = EstadoHE.DETECTADA.value
                    b.aprobado_por_id = None
                    b.aprobado_at = None
                    b.motivo_rechazo = None
                    b.reabierto_por_id = None
                    b.reabierto_at = datetime.now(ART_TZ)
                    b.motivo_reapertura = "Cambio de turno detectado, requiere re-aprobación"
                    self._log_historial(
                        b,
                        accion=_ACCION_RECALCULO_CAMBIO_TURNO,
                        estado_anterior=estado_anterior,
                        estado_nuevo=b.estado,
                        usuario_id=None,
                        motivo="Cambio de turno detectado, requiere re-aprobación",
                        snapshot=snapshot_anterior,
                    )
                    reabiertos += 1
                    # Tras revertir, el bloque queda en `detectada` y se borrará abajo
                    # en el branch `_ESTADOS_EDITABLES` para luego recalcular fresh.
                    self.db.delete(b)
                    continue

                if b.estado in _ESTADOS_EDITABLES + (EstadoHE.ERROR_FICHADAS.value,):
                    # Borrar y recalcular.
                    self.db.delete(b)
                    continue

            self.db.flush()

            # Recalcular el día (excepto si solo había bloques liquidados, en cuyo
            # caso _calcular_he_dia podría querer recrear — pero como hay un bloque
            # liquidado en (emp, fecha, tipo_dia) la unicidad protege).
            tiene_liquidado = any(b.estado == EstadoHE.LIQUIDADA.value for b in existentes)
            if not tiene_liquidado:
                nuevos = self._calcular_he_dia(empleado, d, config)
                for data in nuevos:
                    nb = RRHHHorasExtras(**data)
                    self.db.add(nb)
                    self.db.flush()
                    self._log_historial(
                        nb,
                        accion=_ACCION_RECALCULADA,
                        estado_anterior=None,
                        estado_nuevo=nb.estado,
                        usuario_id=None,
                        motivo="Recálculo por cambio de turno",
                    )
                    recalculados += 1

            d = d + timedelta(days=1)

        self.db.commit()
        logger.info(
            "✅ recalcular_por_cambio_turno empleado=%d procesados=%d "
            "recalculados=%d reabiertos=%d alertas_liquidadas=%d clamped=%d",
            empleado_id,
            procesados,
            recalculados,
            reabiertos,
            alertas_liquidadas,
            dias_clamped,
        )
        return {
            "procesados": procesados,
            "recalculados": recalculados,
            "reabiertos": reabiertos,
            "alertas_liquidadas": alertas_liquidadas,
            "dias_clamped": dias_clamped,
        }

    # ─── T-2.11 — Purga de alertas viejas ───────────────────────────────

    def purgar_alertas_viejas(self, dias: int | None = None) -> dict[str, int]:
        """
        Hard-delete de alertas LEÍDAS (`leida_at IS NOT NULL`) cuya
        `created_at < (today - dias)`.

        - Si `dias` es None, lee `rrhh_horas_extras_config.dias_retencion_alertas`
          (default 15).
        - NUNCA borra alertas no leídas — se conservan hasta resolución manual.

        Returns:
            { purgadas: int, retenidas: int }
        """
        if dias is None:
            config = self._get_config()
            dias = config.dias_retencion_alertas

        if dias < 1:
            raise HTTPException(status_code=422, detail=f"dias debe ser >= 1 (recibido {dias})")

        umbral = datetime.now(ART_TZ) - timedelta(days=dias)

        # Purgables: leídas + viejas.
        purgables_q = self.db.query(RRHHHorasExtrasAlerta).filter(
            RRHHHorasExtrasAlerta.leida_at.isnot(None),
            RRHHHorasExtrasAlerta.created_at < umbral,
        )
        purgadas = purgables_q.count()

        retenidas = (
            self.db.query(func.count(RRHHHorasExtrasAlerta.id))
            .filter(RRHHHorasExtrasAlerta.leida_at.is_(None))
            .scalar()
            or 0
        )

        if purgadas > 0:
            purgables_q.delete(synchronize_session=False)
            self.db.commit()
            logger.info(
                "✅ purgar_alertas_viejas dias=%d purgadas=%d retenidas=%d",
                dias,
                purgadas,
                retenidas,
            )
        else:
            logger.info(
                "🔄 purgar_alertas_viejas dias=%d nada que purgar (retenidas=%d)",
                dias,
                retenidas,
            )

        return {"purgadas": purgadas, "retenidas": int(retenidas)}
