import { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import api from '../services/api';
import styles from './CalendarioEnvios.module.css';

const DIAS_SEMANA = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];

const CORDON_BADGE_CLASS = {
  CABA: styles.badgeCaba,
  'Cordón 1': styles.badgeCordon1,
  'Cordón 2': styles.badgeCordon2,
  'Cordón 3': styles.badgeCordon3,
};

const fmt = (d) => d.toISOString().split('T')[0];

const todayStr = () => fmt(new Date());

/**
 * Calcula el rango de fechas para el modo seleccionado.
 * Semana: lunes a domingo de la semana que contiene `ref`.
 * Quincena: lunes de la semana de `ref` + 13 días (2 semanas).
 * Mes: día 1 al último día del mes de `ref`.
 */
const calcularRango = (ref, modo) => {
  const d = new Date(ref);

  if (modo === 'semana') {
    const day = d.getDay();
    const diff = day === 0 ? -6 : 1 - day; // lunes = 0
    const lunes = new Date(d);
    lunes.setDate(d.getDate() + diff);
    const domingo = new Date(lunes);
    domingo.setDate(lunes.getDate() + 6);
    return { desde: lunes, hasta: domingo };
  }

  if (modo === 'quincena') {
    const day = d.getDay();
    const diff = day === 0 ? -6 : 1 - day;
    const lunes = new Date(d);
    lunes.setDate(d.getDate() + diff);
    const fin = new Date(lunes);
    fin.setDate(lunes.getDate() + 13);
    return { desde: lunes, hasta: fin };
  }

  // mes
  const primero = new Date(d.getFullYear(), d.getMonth(), 1);
  const ultimo = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return { desde: primero, hasta: ultimo };
};

/**
 * Genera todas las celdas del calendario (incluyendo días vacíos de padding).
 * Cada celda: { date: Date | null, dateStr: string | null }
 */
const generarCeldas = (desde, hasta) => {
  const celdas = [];

  // Padding al inicio: días vacíos hasta el lunes
  const diaInicio = desde.getDay();
  const paddingInicio = diaInicio === 0 ? 6 : diaInicio - 1;
  for (let i = 0; i < paddingInicio; i++) {
    celdas.push({ date: null, dateStr: null });
  }

  // Días reales
  const current = new Date(desde);
  while (current <= hasta) {
    celdas.push({ date: new Date(current), dateStr: fmt(current) });
    current.setDate(current.getDate() + 1);
  }

  // Padding al final: completar la última fila de 7
  const resto = celdas.length % 7;
  if (resto > 0) {
    for (let i = 0; i < 7 - resto; i++) {
      celdas.push({ date: null, dateStr: null });
    }
  }

  return celdas;
};

const formatearRangoLabel = (desde, hasta, modo) => {
  const meses = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
  ];

  if (modo === 'mes') {
    return `${meses[desde.getMonth()]} ${desde.getFullYear()}`;
  }

  const dDesde = desde.getDate();
  const dHasta = hasta.getDate();

  if (desde.getMonth() === hasta.getMonth()) {
    return `${dDesde} - ${dHasta} ${meses[desde.getMonth()]} ${desde.getFullYear()}`;
  }

  return `${dDesde} ${meses[desde.getMonth()]} - ${dHasta} ${meses[hasta.getMonth()]} ${hasta.getFullYear()}`;
};


export default function CalendarioEnvios({ onDiaClick, endpointUrl = '/etiquetas-envio/estadisticas-por-dia' }) {
  const [modo, setModo] = useState('semana'); // 'semana' | 'quincena' | 'mes'
  const [refDate, setRefDate] = useState(new Date());
  const [datos, setDatos] = useState({}); // { 'YYYY-MM-DD': { total, flex, manuales, ... } }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const { desde, hasta } = calcularRango(refDate, modo);
  const desdeStr = fmt(desde);
  const hastaStr = fmt(hasta);
  const today = todayStr();

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(endpointUrl, {
        params: {
          fecha_desde: desdeStr,
          fecha_hasta: hastaStr,
        },
      });

      const mapa = {};
      for (const dia of data.dias) {
        mapa[dia.fecha] = dia;
      }
      setDatos(mapa);
    } catch {
      setError('Error cargando datos del calendario');
    } finally {
      setLoading(false);
    }
  }, [desdeStr, hastaStr, endpointUrl]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const navegar = (direccion) => {
    const nueva = new Date(refDate);
    if (modo === 'semana') {
      nueva.setDate(nueva.getDate() + (direccion * 7));
    } else if (modo === 'quincena') {
      nueva.setDate(nueva.getDate() + (direccion * 14));
    } else {
      nueva.setMonth(nueva.getMonth() + direccion);
    }
    setRefDate(nueva);
  };

  const irAHoy = () => {
    setRefDate(new Date());
  };

  const handleDiaClick = (dateStr) => {
    if (dateStr && onDiaClick) {
      onDiaClick(dateStr);
    }
  };

  const celdas = generarCeldas(desde, hasta);

  return (
    <div className={styles.container}>
      {/* Controles */}
      <div className={styles.controls}>
        <div className={styles.rangeToggle}>
          {['semana', 'quincena', 'mes'].map((m) => (
            <button
              key={m}
              type="button"
              className={`${styles.rangeBtn} ${modo === m ? styles.rangeBtnActive : ''}`}
              onClick={() => setModo(m)}
            >
              {m === 'semana' ? 'Semana' : m === 'quincena' ? 'Quincena' : 'Mes'}
            </button>
          ))}
        </div>

        <div className={styles.navGroup}>
          <button
            type="button"
            className={styles.navBtn}
            onClick={() => navegar(-1)}
            aria-label="Período anterior"
          >
            <ChevronLeft size={16} />
          </button>

          <button
            type="button"
            className={styles.rangeBtn}
            onClick={irAHoy}
          >
            Hoy
          </button>

          <span className={styles.rangeLabel}>
            {formatearRangoLabel(desde, hasta, modo)}
          </span>

          <button
            type="button"
            className={styles.navBtn}
            onClick={() => navegar(1)}
            aria-label="Período siguiente"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Loading / Error */}
      {loading && <div className={styles.loading}>Cargando calendario...</div>}
      {error && <div className={styles.error}>{error}</div>}

      {/* Grid */}
      {!loading && !error && (
        <div className={styles.calendarGrid}>
          {/* Headers */}
          {DIAS_SEMANA.map((dia) => (
            <div key={dia} className={styles.dayHeader}>{dia}</div>
          ))}

          {/* Celdas */}
          {celdas.map((celda, idx) => {
            if (!celda.date) {
              return <div key={`empty-${idx}`} className={styles.dayCellEmpty} />;
            }

            const dia = datos[celda.dateStr];
            const isToday = celda.dateStr === today;

            return (
              <div
                key={celda.dateStr}
                className={`${styles.dayCell} ${isToday ? styles.dayCellToday : ''}`}
                onClick={() => handleDiaClick(celda.dateStr)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleDiaClick(celda.dateStr);
                  }
                }}
                aria-label={`Ver envíos del ${celda.dateStr}`}
              >
                <div className={`${styles.dayNumber} ${isToday ? styles.dayNumberToday : ''}`}>
                  {celda.date.getDate()}
                </div>

                {dia && dia.total > 0 && (
                  <div className={styles.dayBadges}>
                    {/* Total */}
                    <div className={styles.dayTotal}>{dia.total}</div>

                    {/* Tipo: Flex / Manual */}
                    <div className={styles.badgeRow}>
                      {dia.flex > 0 && (
                        <span className={`${styles.badge} ${styles.badgeFlex}`}>
                          Flex {dia.flex}
                        </span>
                      )}
                      {dia.manuales > 0 && (
                        <span className={`${styles.badge} ${styles.badgeManual}`}>
                          Manual {dia.manuales}
                        </span>
                      )}
                    </div>

                    {/* Cordones */}
                    <div className={styles.badgeRow}>
                      {Object.entries(dia.por_cordon).map(([cordon, cant]) => (
                        <span
                          key={cordon}
                          className={`${styles.badge} ${CORDON_BADGE_CLASS[cordon] || styles.badgeSinCordon}`}
                        >
                          {cordon === 'CABA' ? 'CABA' : cordon.replace('Cordón ', 'C')} {cant}
                        </span>
                      ))}
                      {dia.sin_cordon > 0 && (
                        <span className={`${styles.badge} ${styles.badgeSinCordon}`}>
                          S/C {dia.sin_cordon}
                        </span>
                      )}
                    </div>

                    {/* Logística */}
                    <div className={styles.badgeRow}>
                      {dia.con_logistica > 0 && (
                        <span className={`${styles.badge} ${styles.badgeConLog}`}>
                          Log {dia.con_logistica}
                        </span>
                      )}
                      {dia.sin_logistica > 0 && (
                        <span className={`${styles.badge} ${styles.badgeSinLog}`}>
                          S/Log {dia.sin_logistica}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
