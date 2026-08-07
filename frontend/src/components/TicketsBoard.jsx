import { useState, useEffect, useCallback } from 'react';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core';
import { boardAPI, ticketsAPI } from '../services/api';
import { handleDragEnd } from './ticketsBoardDnd';
import TicketCard from './TicketCard';
import styles from './TicketsBoard.module.css';

const ITEMS_POR_COLUMNA = 20;

/** Wraps a card with dnd-kit's `useDraggable` — the attributes/listeners are
 * applied directly onto `TicketCard`'s own `<button>`, not a wrapping div. */
function DraggableCard({ ticket, columnaClave, onClick }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `card-${ticket.id}`,
    data: { ticketId: ticket.id, columnaClave },
  });

  return (
    <TicketCard
      ticket={ticket}
      onClick={onClick}
      dragRef={setNodeRef}
      dragAttributes={attributes}
      dragListeners={listeners}
      isDragging={isDragging}
    />
  );
}

/** A column's item list as a dnd-kit droppable target, keyed by `columna.clave`. */
function DroppableColumn({ columna, children }) {
  const { setNodeRef, isOver } = useDroppable({ id: columna.clave });

  return (
    <div ref={setNodeRef} className={isOver ? `${styles.columnItems} ${styles.columnItemsOver}` : styles.columnItems}>
      {children}
    </div>
  );
}

/**
 * Board with drag-and-drop write semantics (tickets-ai-triage PR 5c).
 * "Load more" reuses GET /tickets with a matching filter, never a second
 * board query — pagination has exactly one implementation (PR 5b).
 */
export default function TicketsBoard({ agrupacion, onCardClick }) {
  const [columnas, setColumnas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dragError, setDragError] = useState(null);
  const [loadingMore, setLoadingMore] = useState({});
  const [paginas, setPaginas] = useState({});

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor)
  );

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

  const onDragEnd = useCallback(
    (event) => handleDragEnd(event, { columnas, agrupacion, setColumnas, onError: setDragError }),
    [columnas, agrupacion]
  );

  if (loading) return <div className={styles.loading}>Cargando tablero...</div>;
  if (error) return <div className={styles.error}>{error}</div>;

  return (
    <div className={styles.boardWrapper}>
      {dragError && <div className={styles.dragError}>{dragError}</div>}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <div className={styles.board}>
          {columnas.map((columna) => (
            <div key={columna.clave} className={styles.column}>
              <div className={styles.columnHeader}>
                <span
                  className={styles.columnDot}
                  style={{ background: columna.color || 'var(--cf-text-tertiary)' }}
                />
                <span className={styles.columnTitle}>{columna.etiqueta}</span>
                <span className={styles.columnCount}>{columna.total}</span>
              </div>
              <DroppableColumn columna={columna}>
                {columna.items.map((ticket) => (
                  <DraggableCard key={ticket.id} ticket={ticket} columnaClave={columna.clave} onClick={onCardClick} />
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
              </DroppableColumn>
            </div>
          ))}
        </div>
      </DndContext>
    </div>
  );
}
