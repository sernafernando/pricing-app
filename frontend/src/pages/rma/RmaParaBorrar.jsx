import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../../services/api';
import rmaStyles from '../Rma.module.css';
import styles from './RmaParaBorrar.module.css';

// "Para borrar": cases marked "Marcado para borrar pedido". Pendientes (default) hides the ones someone already ticked
// as "Revisado"; the tick needs rma.gestionar, so without it the column shows who reviewed and when, read-only.
const FILTROS = [
  { value: 'pendientes', label: 'Pendientes' },
  { value: 'revisados', label: 'Revisados' },
  { value: 'todos', label: 'Todos' },
];

const formatFecha = (iso) => (iso ? new Date(iso).toLocaleDateString('es-AR') : '—');

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

  const toggleRevisado = async (caso) => {
    setGuardando(caso.id);
    setError(null);
    try {
      await api.put(`/rma-seguimiento/${caso.id}/borrar-revisado`, { revisado: !caso.borrar_revisado_at });
      setRecarga((n) => n + 1);
    } catch {
      setError(`No se pudo guardar la revisión de ${caso.numero_caso}.`);
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
        <table className="table-tesla striped">
          <thead className="table-tesla-head">
            <tr>
              <th>Caso</th>
              <th>Fecha</th>
              <th>Cliente</th>
              <th>ML ID</th>
              <th>Estado</th>
              <th>Revisado</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {loading ? (
              <tr>
                <td colSpan={6} className={rmaStyles.loadingCell}>
                  Cargando...
                </td>
              </tr>
            ) : data.items.length === 0 ? (
              <tr>
                <td colSpan={6} className={rmaStyles.emptyCell}>
                  No hay casos para borrar en este filtro
                </td>
              </tr>
            ) : (
              data.items.map((caso) => (
                <tr key={caso.id}>
                  <td className={rmaStyles.cellCaso}>{caso.numero_caso}</td>
                  <td>{formatFecha(caso.fecha_caso || caso.created_at)}</td>
                  <td>{caso.cliente_nombre || '—'}</td>
                  <td>{caso.ml_id || '—'}</td>
                  <td>{caso.estado || '—'}</td>
                  <td>
                    <span className={styles.revisado}>
                      {puedeGestionar && (
                        <input
                          type="checkbox"
                          checked={Boolean(caso.borrar_revisado_at)}
                          disabled={guardando === caso.id}
                          onChange={() => toggleRevisado(caso)}
                          aria-label={`Revisado ${caso.numero_caso}`}
                        />
                      )}
                      {caso.borrar_revisado_at && (
                        <span className={styles.quien}>
                          {caso.borrar_revisado_por_nombre || 'Revisado'} · {formatFecha(caso.borrar_revisado_at)}
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
