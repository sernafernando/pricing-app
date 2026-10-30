import { useCallback, useEffect, useRef, useState } from 'react';
import { offsetGruposAPI } from '../../services/offsetGruposAPI';

/**
 * The offset groups with what each reaches (`GET /offset-grupos` + `GET /offset-grupos-alcance`) and the filter
 * options (asked once). `recargar` asks the groups and their reach again: every change calls it, so the preview
 * follows the filters.
 */
export function useGrupos() {
  const [grupos, setGrupos] = useState(null);
  const [opciones, setOpciones] = useState(null);
  const [error, setError] = useState(null);
  const requestRef = useRef(0);
  const opcionesRef = useRef(null);
  const recargar = useCallback(async () => {
    const requestId = ++requestRef.current;
    opcionesRef.current ??= offsetGruposAPI
      .opciones()
      .then(({ data }) => data)
      .catch(() => null);
    try {
      const [lista, alcance, opts] = await Promise.all([offsetGruposAPI.listar(), offsetGruposAPI.alcance(), opcionesRef.current]);
      if (requestId !== requestRef.current) return;
      const porGrupo = Object.fromEntries((alcance.data ?? []).map((a) => [a.grupo_id, a]));
      setGrupos((lista.data ?? []).map((g) => ({ ...g, productos: porGrupo[g.id]?.productos ?? 0, campanas: porGrupo[g.id]?.campanas ?? [] })));
      setOpciones(opts);
      setError(null);
    } catch {
      if (requestId === requestRef.current) setError('No se pudieron cargar los grupos.');
    }
  }, []);
  useEffect(() => {
    recargar();
  }, [recargar]);
  return { grupos, opciones, error, recargar };
}
