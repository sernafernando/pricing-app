import { ticketsAPI } from '../services/api';

const URGENCIA_SIN_CLASIFICAR = 'sin_clasificar';

/**
 * Moves a card between two columns in the board's local state. Pure — no
 * API call, no side effect. Used both for the optimistic move and, with
 * `desde`/`hacia` swapped, as the rollback on a failed write.
 */
export function moverTicketEntreColumnas(columnas, ticketId, desde, hacia) {
  const origen = columnas.find((c) => c.clave === desde);
  const ticket = origen?.items.find((t) => t.id === ticketId);
  if (!ticket) return columnas;

  return columnas.map((c) => {
    if (c.clave === desde) return { ...c, items: c.items.filter((t) => t.id !== ticketId), total: c.total - 1 };
    if (c.clave === hacia) return { ...c, items: [...c.items, ticket], total: c.total + 1 };
    return c;
  });
}

/**
 * Drop write semantics (design #1303 §4 / obs #1301): dropping on a
 * different STATE column transitions the workflow graph; dropping on a
 * different URGENCY column PATCHes urgencia manually. Dropping within the
 * SAME column makes no API call and is never persisted — no order column
 * exists, so a same-column drop is a pure no-op here (the board's local
 * state doesn't even reorder within a column).
 *
 * Exported as a plain function, in its own module (not the component file,
 * so `react-refresh/only-export-components` stays satisfied) per the
 * slice's hard constraint: dnd-kit drag gestures don't work in jsdom, so
 * this is tested by feeding it synthetic dnd-kit event objects directly —
 * never by simulating the gesture.
 */
export async function handleDragEnd(event, { columnas, agrupacion, setColumnas, onError }) {
  const { active, over } = event;
  if (!over) return;

  const ticketId = active?.data?.current?.ticketId;
  const columnaOrigen = active?.data?.current?.columnaClave;
  const columnaDestino = over.id;

  if (ticketId == null || !columnaOrigen || columnaOrigen === columnaDestino) {
    return;
  }

  // The 'inbox' column aggregates every estado in the Inbox workflow — it
  // has no single target estado_id to transition into. Without this guard
  // `Number('inbox')` is NaN, which serializes to `nuevo_estado_id: null`
  // and always 422s after an optimistic move the user then sees revert.
  if (agrupacion === 'estado' && columnaDestino === 'inbox') {
    onError?.('No se puede mover un ticket directamente a la Bandeja de entrada');
    return;
  }

  setColumnas(moverTicketEntreColumnas(columnas, ticketId, columnaOrigen, columnaDestino));

  try {
    if (agrupacion === 'estado') {
      await ticketsAPI.transicion(ticketId, { nuevo_estado_id: Number(columnaDestino) });
    } else {
      const urgencia = columnaDestino === URGENCIA_SIN_CLASIFICAR ? null : columnaDestino;
      await ticketsAPI.actualizar(ticketId, { urgencia, urgencia_origen: 'humano' });
    }
  } catch (err) {
    setColumnas(columnas);
    onError?.(err.response?.data?.detail || 'No se pudo mover el ticket');
  }
}
