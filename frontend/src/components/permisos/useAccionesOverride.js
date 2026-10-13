import { useState } from 'react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';

const PERMISO_GESTIONAR = 'admin.gestionar_permisos';
const MOTIVO_OVERRIDE = 'Override desde panel de permisos';

/**
 * Conceder / Quitar / Resetear overrides of one user, shared by the
 * "Por pantalla" and "Por permiso" views.
 *
 * Editing needs `admin.gestionar_permisos` (the backend gate of the override
 * endpoints) and is never offered on a SUPERADMIN target. After a change it
 * awaits `onActualizado()` (the parent reloads the payload) and only then
 * announces success through `onMensaje`.
 *
 * `bloqueo` ({ enCurso, setEnCurso }) lets the parent own the one-action-at-a-
 * time lock, so it survives switching between views; without it the lock is
 * local to the calling view.
 */
export default function useAccionesOverride({ usuarioId, rol, onActualizado, onMensaje, bloqueo }) {
  const { tienePermiso } = usePermisos();
  const [enCursoLocal, setEnCursoLocal] = useState(null);
  const { enCurso, setEnCurso } = bloqueo ?? { enCurso: enCursoLocal, setEnCurso: setEnCursoLocal };
  const puedeEditar = tienePermiso(PERMISO_GESTIONAR) && rol !== 'SUPERADMIN';

  const ejecutar = async (codigo, accion, textoOk, textoError) => {
    setEnCurso(codigo);
    try {
      await accion();
    } catch (error) {
      onMensaje?.({ tipo: 'error', texto: error?.response?.data?.detail || textoError });
      setEnCurso(null);
      return;
    }
    // Success is announced only once the list shows it; a failed reload gets
    // its own message instead (the change itself was saved).
    try {
      await onActualizado?.();
      onMensaje?.({ tipo: 'success', texto: textoOk });
    } catch {
      onMensaje?.({ tipo: 'error', texto: 'El cambio se guardó, pero no se pudo recargar la lista de permisos' });
    } finally {
      setEnCurso(null);
    }
  };

  const forzar = (codigo, concedido) =>
    ejecutar(
      codigo,
      () =>
        api.post('/permisos/override', {
          usuario_id: usuarioId,
          permiso_codigo: codigo,
          concedido,
          motivo: MOTIVO_OVERRIDE,
        }),
      concedido ? 'Permiso concedido' : 'Permiso quitado',
      'Error al modificar permiso',
    );

  const resetear = (codigo) =>
    ejecutar(
      codigo,
      () => api.delete(`/permisos/override/${usuarioId}/${codigo}`),
      'Vuelto al permiso base del rol',
      'Error al resetear permiso',
    );

  return { puedeEditar, enCurso, forzar, resetear };
}
