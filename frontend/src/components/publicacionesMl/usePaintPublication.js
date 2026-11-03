import { useCallback } from 'react';
import { usePermisos } from '../../contexts/PermisosContext';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { paintPublications } from './paintPublications';

/**
 * Paints one publication on its own on the layer on show (seleccion-por-publicacion S3), never its product: the
 * keyboard's quick colors on a publication row. Productos' rule for one row -- the global layer needs
 * `productos.marcar_color`, a team layer membership (the backend checks it again). On success `onPainted` gets the
 * change shaped as `publicacion_color:changed`; on failure nothing changes and `showToast` says why.
 */
export default function usePaintPublication({ equipo, onPainted, showToast }) {
  const { tienePermiso } = usePermisos();
  const allowed = equipo ? true : tienePermiso('productos.marcar_color');

  return useCallback(
    async (itemId, color) => {
      if (!allowed) {
        showToast?.('No tenés permiso para marcar colores en la capa Global', 'error');
        return;
      }
      try {
        await paintPublications([itemId], color, equipo ? Number(equipo) : null, onPainted);
      } catch (error) {
        showToast?.(apiErrorMessage(error, 'No se pudo pintar la publicación'), 'error');
      }
    },
    [allowed, equipo, onPainted, showToast],
  );
}
