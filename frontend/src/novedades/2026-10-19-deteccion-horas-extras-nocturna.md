# Horas Extras: la detección vuelve a correr sola todas las noches

Área: RRHH

## Resumen ejecutivo

La detección de horas extras vuelve a correr sola todas las noches, a las 03:30, y procesa el día anterior. No hace falta recalcular a mano para que aparezcan las horas extras de cada día.

- **Todas las noches:** a las 03:30 se detectan las horas extras del día anterior.
- **No se pierden días:** si una noche la detección falla, se reintenta, y ese día se procesa igual.
- **Recalcular sin trabas:** el botón **Recalcular período** ya no queda trabado con el aviso "Cron en curso". Solo avisa cuando de verdad hay otra detección en curso, con el mensaje "Otra detección de horas extras está en curso. Intentá de nuevo en unos minutos."

## Cómo se usa

1. Abrir **RRHH → Horas Extras**.
2. Revisar las horas extras del día anterior: ya están detectadas desde la madrugada.
3. Para volver a procesar un período, hacer clic en **Recalcular período**.
4. Si aparece el aviso de otra detección en curso, esperar unos minutos y volver a intentar.
