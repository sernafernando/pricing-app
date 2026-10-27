import { useCallback } from 'react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { apiErrorMessage } from '../../utils/apiErrorMessage';

/**
 * Paints one product on the layer on show (S8), as Productos' quick colors do: `PATCH /productos/{id}/color` with
 * the team in the query (`equipo_id`; omitted = the global layer) and Productos' rule -- the global layer needs
 * `productos.marcar_color`, a team layer membership (the backend checks it again). On success `onPainted` gets the
 * change shaped as the SSE event Productos publishes; on failure nothing changes and `showToast` says why.
 */
export default function usePaintProduct({ equipo, onPainted, showToast }) {
  const { tienePermiso } = usePermisos();
  const allowed = equipo ? true : tienePermiso('productos.marcar_color');

  return useCallback(
    async (productId, color) => {
      if (!allowed) {
        showToast?.('No tenés permiso para marcar colores en la capa Global', 'error');
        return;
      }
      const equipoId = equipo ? Number(equipo) : null;
      try {
        await api.patch(`/productos/${productId}/color`, { color }, { params: equipoId === null ? {} : { equipo_id: equipoId } });
        onPainted({ data: { vista: 'ml', is_global: equipoId === null, equipo_id: equipoId, item_ids: [productId], color } });
      } catch (error) {
        showToast?.(apiErrorMessage(error, 'No se pudo pintar el producto'), 'error');
      }
    },
    [allowed, equipo, onPainted, showToast],
  );
}
