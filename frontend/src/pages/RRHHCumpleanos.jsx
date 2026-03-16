import { useState, useEffect, useCallback } from 'react';
import { rrhhAPI } from '../services/api';
import styles from './RRHHCumpleanos.module.css';
import { ChevronLeft, ChevronRight, Cake, Gift, PartyPopper } from 'lucide-react';

const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
];

const DIAS_SEMANA = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];

export default function RRHHCumpleanos() {
  const hoy = new Date();
  const [mes, setMes] = useState(hoy.getMonth() + 1);
  const [anio, setAnio] = useState(hoy.getFullYear());
  const [cumpleanos, setCumpleanos] = useState([]);
  const [loading, setLoading] = useState(false);

  const cargarCumpleanos = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await rrhhAPI.listarCumpleanosMes({ mes, anio });
      setCumpleanos(Array.isArray(data) ? data : []);
    } catch {
      setCumpleanos([]);
    } finally {
      setLoading(false);
    }
  }, [mes, anio]);

  useEffect(() => {
    cargarCumpleanos();
  }, [cargarCumpleanos]);

  const handleMesAnterior = () => {
    if (mes === 1) {
      setMes(12);
      setAnio((a) => a - 1);
    } else {
      setMes((m) => m - 1);
    }
  };

  const handleMesSiguiente = () => {
    if (mes === 12) {
      setMes(1);
      setAnio((a) => a + 1);
    } else {
      setMes((m) => m + 1);
    }
  };

  const handleHoy = () => {
    setMes(hoy.getMonth() + 1);
    setAnio(hoy.getFullYear());
  };

  // Generar grilla del calendario
  const primerDia = new Date(anio, mes - 1, 1);
  const ultimoDia = new Date(anio, mes, 0);
  const diasEnMes = ultimoDia.getDate();
  // getDay(): 0=Dom ... 6=Sab → convertir a 0=Lun ... 6=Dom
  const offsetInicio = (primerDia.getDay() + 6) % 7;

  // Mapear cumpleaños por día
  const cumplePorDia = {};
  for (const c of cumpleanos) {
    const dia = c.dia;
    if (!cumplePorDia[dia]) cumplePorDia[dia] = [];
    cumplePorDia[dia].push(c);
  }

  const esHoy = (dia) =>
    dia === hoy.getDate() && mes === hoy.getMonth() + 1 && anio === hoy.getFullYear();

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Cake size={24} />
          <h1>Cumpleaños</h1>
          <span className={styles.badge}>{cumpleanos.length} este mes</span>
        </div>
      </div>

      {/* Nav mes */}
      <div className={styles.mesNav}>
        <button className={styles.btnNav} onClick={handleMesAnterior}>
          <ChevronLeft size={20} />
        </button>
        <button className={styles.mesLabel} onClick={handleHoy}>
          {MESES[mes - 1]} {anio}
        </button>
        <button className={styles.btnNav} onClick={handleMesSiguiente}>
          <ChevronRight size={20} />
        </button>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando cumpleaños...</div>
      ) : (
        <>
          {/* Calendario */}
          <div className={styles.calendario}>
            {/* Header días semana */}
            {DIAS_SEMANA.map((d) => (
              <div key={d} className={styles.diaSemanaHeader}>{d}</div>
            ))}

            {/* Celdas vacías antes del primer día */}
            {Array.from({ length: offsetInicio }).map((_, i) => (
              <div key={`empty-${i}`} className={styles.celdaVacia} />
            ))}

            {/* Celdas de días */}
            {Array.from({ length: diasEnMes }).map((_, i) => {
              const dia = i + 1;
              const cumples = cumplePorDia[dia] || [];
              const tieneCumple = cumples.length > 0;

              return (
                <div
                  key={dia}
                  className={`${styles.celda} ${esHoy(dia) ? styles.celdaHoy : ''} ${tieneCumple ? styles.celdaCumple : ''}`}
                >
                  <span className={styles.diaNumero}>{dia}</span>
                  {tieneCumple && (
                    <div className={styles.cumpleList}>
                      {cumples.map((c) => (
                        <div key={c.empleado_id} className={styles.cumpleItem}>
                          <Gift size={10} />
                          <span className={styles.cumpleNombre}>
                            {c.nombre} {c.apellido}
                          </span>
                          {c.edad && (
                            <span className={styles.cumpleEdad}>{c.edad}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Lista lateral de cumpleaños del mes */}
          {cumpleanos.length > 0 && (
            <div className={styles.listaMes}>
              <h3 className={styles.listaTitle}>
                <PartyPopper size={16} /> Cumpleaños de {MESES[mes - 1]}
              </h3>
              <div className={styles.listaItems}>
                {cumpleanos.map((c) => (
                  <div
                    key={c.empleado_id}
                    className={`${styles.listaItem} ${esHoy(c.dia) ? styles.listaItemHoy : ''}`}
                  >
                    <span className={styles.listaItemDia}>{c.dia}</span>
                    <div className={styles.listaItemInfo}>
                      <span className={styles.listaItemNombre}>
                        {c.apellido}, {c.nombre}
                      </span>
                      <span className={styles.listaItemMeta}>
                        {c.area || 'Sin área'}
                        {c.edad ? ` — Cumple ${c.edad} años` : ''}
                      </span>
                    </div>
                    {esHoy(c.dia) && <Cake size={14} className={styles.cakeIcon} />}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
