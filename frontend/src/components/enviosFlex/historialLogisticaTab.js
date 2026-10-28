import { useEffect, useRef } from 'react';

// Row patch after an undo: name and color come from the logísticas list, like a
// normal reassignment, so the row is right even if the backend went elsewhere.
export const aplicarDeshacer = (etiquetas, shippingId, logisticaId, logisticas) => {
  const log = logisticas.find((l) => l.id === logisticaId);
  return etiquetas.map((e) =>
    e.shipping_id === shippingId
      ? {
          ...e,
          logistica_id: logisticaId,
          logistica_nombre: log?.nombre || null,
          logistica_color: log?.color || null,
        }
      : e,
  );
};

// The open history modal pauses the SSE reload; reload once when it closes so the
// table catches up with changes made meanwhile (for example after a 409 on undo).
export const useRecargarAlCerrar = (abierto, recargar) => {
  const estuvoAbierto = useRef(false);
  useEffect(() => {
    if (abierto) {
      estuvoAbierto.current = true;
    } else if (estuvoAbierto.current) {
      estuvoAbierto.current = false;
      recargar();
    }
  }, [abierto, recargar]);
};
