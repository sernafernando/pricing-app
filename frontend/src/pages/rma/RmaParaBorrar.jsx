import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../../services/api';
import rmaStyles from '../Rma.module.css';
import styles from './RmaParaBorrar.module.css';

// "Para borrar": cases marked "Marcado para borrar pedido", one row per ML operation (two RMAs of the same sale are
// one row, with its cases, articles and the shipping number from our stored ML orders). Pendientes (default) hides
// the operations whose cases were all ticked as "Revisado"; the row's tick reviews every case of the row and needs
// rma.gestionar, so without it the column shows who reviewed and when, read-only.
const FILTROS = [
  { value: 'pendientes', label: 'Pendientes' },
  { value: 'revisados', label: 'Revisados' },
  { value: 'todos', label: 'Todos' },
];

// A date-only value ("2026-11-01", fecha_caso) is a calendar day: `new Date` would read it as UTC midnight and show
// the day before in Argentina, so it is formatted as is. Timestamps (created_at, borrar_revisado_at) go through Date.
const COLUMNAS = 8;

const DIA = /^(\d{4})-(\d{2})-(\d{2})$/;
const formatFecha = (iso) => {
  if (!iso) return '—';
  const dia = DIA.exec(iso);
  if (dia) return `${dia[3]}/${dia[2]}/${dia[1]}`;
  return new Date(iso).toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

const numerosDe = (operacion) => operacion.casos.map((c) => c.numero_caso).join(', ');

// The cases' own values, once each and in the row's order: an operation's cases usually share them.
const distintos = (valores) => [...new Set(valores.filter(Boolean))];

// The newest review of the row, to say who and when once all its cases are reviewed.
const ultimaRevision = (casos) =>
  casos
    .filter((c) => c.borrar_revisado_at)
    .reduce((ultima, c) => (!ultima || c.borrar_revisado_at > ultima.borrar_revisado_at ? c : ultima), null);

function Revision({ operacion }) {
  const revisados = operacion.casos.filter((c) => c.borrar_revisado_at).length;
  if (!revisados) return null;
  if (revisados < operacion.casos.length) {
    return <span className={styles.quien}>{`${revisados} de ${operacion.casos.length} revisados`}</span>;
  }
  const ultima = ultimaRevision(operacion.casos);
  return (
    <span className={styles.quien}>
      {ultima.borrar_revisado_por_nombre || 'Revisado'} · {formatFecha(ultima.borrar_revisado_at)}
    </span>
  );
}

export default function RmaParaBorrar({ puedeGestionar }) {
  const [estado, setEstado] = useState('pendientes');
  const [data, setData] = useState({ items: [], counts: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [guardando, setGuardando] = useState(null);
  // Bumped after a tick: the effect reloads with the filter selected NOW, even if it changed while the PUT ran.
  const [recarga, setRecarga] = useState(0);
  // Only the latest request may fill the table: an older answer that arrives late (a quick filter change) is dropped.
  const ultimoPedido = useRef(0);

  const cargar = useCallback(async () => {
    const pedido = ++ultimoPedido.current;
    setLoading(true);
    setError(null);
    try {
      const { data: body } = await api.get('/rma-seguimiento/para-borrar', { params: { estado } });
      if (pedido === ultimoPedido.current) setData(body);
    } catch {
      if (pedido === ultimoPedido.current) setError('No se pudo cargar la lista de casos para borrar.');
    } finally {
      if (pedido === ultimoPedido.current) setLoading(false);
    }
  }, [estado]);

  useEffect(() => {
    cargar();
  }, [cargar, recarga]);

  const toggleRevisado = async (operacion) => {
    setGuardando(operacion.clave);
    setError(null);
    try {
      const { data: guardados } = await api.put('/rma-seguimiento/para-borrar/revisado', {
        caso_ids: operacion.casos.map((c) => c.id),
        revisado: !operacion.revisado,
      });
      // The row shows the saved tick right away, so a second click before the reload lands toggles it back.
      const porId = new Map(guardados.map((c) => [c.id, c]));
      setData((prev) => ({
        ...prev,
        items: prev.items.map((op) => {
          if (op.clave !== operacion.clave) return op;
          const casos = op.casos.map((c) => (porId.has(c.id) ? { ...c, ...porId.get(c.id) } : c));
          return { ...op, casos, revisado: casos.every((c) => c.borrar_revisado_at) };
        }),
      }));
      setRecarga((n) => n + 1);
    } catch {
      setError(`No se pudo guardar la revisión de ${numerosDe(operacion)}.`);
    } finally {
      setGuardando(null);
    }
  };

  return (
    <>
      <div className={rmaStyles.filtros} role="group" aria-label="Filtrar casos para borrar">
        {FILTROS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`btn-tesla outline sm ${styles.filtro}`}
            aria-pressed={estado === f.value}
            onClick={() => setEstado(f.value)}
          >
            {data.counts ? `${f.label} (${data.counts[f.value]})` : f.label}
          </button>
        ))}
      </div>

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      <div className="table-container-tesla">
        <table className="table-tesla striped" aria-busy={loading}>
          <thead className="table-tesla-head">
            <tr>
              <th>Caso</th>
              <th>Fecha</th>
              <th>Cliente</th>
              <th>ML ID</th>
              <th>Envío</th>
              <th>Artículos</th>
              <th>Estado</th>
              <th>Revisado</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {loading && !data.counts ? (
              <tr>
                <td colSpan={COLUMNAS} className={rmaStyles.loadingCell}>
                  Cargando...
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan={COLUMNAS} className={rmaStyles.emptyCell}>
                  No hay casos para borrar en este filtro
                </td>
              </tr>
            ) : (
              data.items.map((operacion) => {
                const primero = operacion.casos[operacion.casos.length - 1];
                return (
                  <tr key={operacion.clave}>
                    <td className={rmaStyles.cellCaso}>
                      <ul className={styles.lista}>
                        {operacion.casos.map((c) => (
                          <li key={c.id}>{c.numero_caso}</li>
                        ))}
                      </ul>
                    </td>
                    <td>{formatFecha(primero.fecha_caso || primero.created_at)}</td>
                    <td>{operacion.cliente_nombre || '—'}</td>
                    <td>{operacion.ml_id || '—'}</td>
                    <td>{operacion.numero_envio || '—'}</td>
                    <td>
                      <ul className={styles.lista}>
                        {distintos(operacion.casos.flatMap((c) => c.articulos ?? [])).map((articulo) => (
                          <li key={articulo}>{articulo}</li>
                        ))}
                      </ul>
                    </td>
                    <td>{distintos(operacion.casos.map((c) => c.estado)).join(', ') || '—'}</td>
                    <td>
                      <span className={styles.revisado}>
                        {puedeGestionar && (
                          <input
                            type="checkbox"
                            checked={operacion.revisado}
                            disabled={guardando === operacion.clave}
                            onChange={() => toggleRevisado(operacion)}
                            aria-label={`Revisado ${numerosDe(operacion)}`}
                          />
                        )}
                        <Revision operacion={operacion} />
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
