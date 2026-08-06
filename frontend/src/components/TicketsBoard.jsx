import { useState, useEffect, useCallback } from 'react';
import { boardAPI, ticketsAPI } from '../services/api';
import TicketCard from './TicketCard';
import styles from './TicketsBoard.module.css';

const ITEMS_POR_COLUMNA = 20;

/**
 * Read-only board (tickets-ai-triage PR 5b). No drag-and-drop — that is
 * PR 5c. "Load more" reuses GET /tickets with a matching filter, never a
 * second board query — pagination has exactly one implementation.
 */
export default function TicketsBoard({ agrupacion, onCardClick }) {
  const [columnas, setColumnas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loadingMore, setLoadingMore] = useState({});
  const [paginas, setPaginas] = useState({});

  const cargarTablero = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await boardAPI.obtener(agrupacion, ITEMS_POR_COLUMNA);
      setColumnas(data.columnas || []);
      setPaginas({});
    } catch {
      setColumnas([]);
      setError('Error al cargar el tablero');
    } finally {
      setLoading(false);
    }
  }, [agrupacion]);

  useEffect(() => {
    cargarTablero();
  }, [cargarTablero]);

  const handleLoadMore = async (columna) => {
    const nextPage = (paginas[columna.clave] || 1) + 1;
    setLoadingMore((prev) => ({ ...prev, [columna.clave]: true }));
    try {
      const filtro = agrupacion === 'estado' ? { estado_id: columna.clave } : { urgencia: columna.clave };
      const { data } = await ticketsAPI.listar({ ...filtro, page: nextPage, page_size: ITEMS_POR_COLUMNA });
      setColumnas((prev) =>
        prev.map((c) => (c.clave === columna.clave ? { ...c, items: [...c.items, ...(data.items || [])] } : c))
      );
      setPaginas((prev) => ({ ...prev, [columna.clave]: nextPage }));
    } catch {
      // Non-blocking — the column just stops offering more this attempt.
    } finally {
      setLoadingMore((prev) => ({ ...prev, [columna.clave]: false }));
    }
  };

  if (loading) return <div className={styles.loading}>Cargando tablero...</div>;
  if (error) return <div className={styles.error}>{error}</div>;

  return (
    <div className={styles.board}>
      {columnas.map((columna) => (
        <div key={columna.clave} className={styles.column}>
          <div className={styles.columnHeader}>
            <span className={styles.columnDot} style={{ background: columna.color || 'var(--cf-text-tertiary)' }} />
            <span className={styles.columnTitle}>{columna.etiqueta}</span>
            <span className={styles.columnCount}>{columna.total}</span>
          </div>
          <div className={styles.columnItems}>
            {columna.items.map((ticket) => (
              <TicketCard key={ticket.id} ticket={ticket} onClick={onCardClick} />
            ))}
            {columna.total > columna.items.length && (
              <button
                type="button"
                className={styles.btnLoadMore}
                onClick={() => handleLoadMore(columna)}
                disabled={loadingMore[columna.clave]}
              >
                {loadingMore[columna.clave] ? 'Cargando...' : 'Cargar más'}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
