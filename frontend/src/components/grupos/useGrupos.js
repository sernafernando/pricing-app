import { useCallback, useEffect, useRef, useState } from 'react';
import { offsetGruposAPI } from '../../services/offsetGruposAPI';

/**
 * The offset groups with what each reaches (`GET /offset-grupos` + `GET /offset-grupos-alcance`) and the filter
 * options (asked once, again after a failure). A new `version` reloads. `recargar` asks the groups and their
 * reach again: every change calls it, so the preview follows the filters.
 */
export function useGrupos(version = 0) {
  const [grupos, setGrupos] = useState(null);
  const [opciones, setOpciones] = useState(null);
  const [error, setError] = useState(null);
  const [errorOpciones, setErrorOpciones] = useState(null);
  const requestRef = useRef(0);
  const opcionesRef = useRef(null);
  const recargar = useCallback(async () => {
    const requestId = ++requestRef.current;
    // Asked once; a failure is forgotten so the next reload asks again.
    opcionesRef.current ??= offsetGruposAPI
      .opciones()
      .then(({ data }) => ({ data }))
      .catch(() => {
        opcionesRef.current = null;
        return { fallo: true };
      });
    try {
      const [lista, alcance, opts] = await Promise.all([offsetGruposAPI.listar(), offsetGruposAPI.alcance(), opcionesRef.current]);
      if (requestId !== requestRef.current) return;
      const porGrupo = Object.fromEntries((alcance.data ?? []).map((a) => [a.grupo_id, a]));
      setGrupos((lista.data ?? []).map((g) => ({ ...g, productos: porGrupo[g.id]?.productos ?? 0, campanas: porGrupo[g.id]?.campanas ?? [] })));
      if (opts.fallo) {
        setErrorOpciones('No se pudieron cargar las marcas, categorías y subcategorías para los filtros. Tocá Actualizar para reintentar.');
      } else {
        setOpciones(opts.data);
        setErrorOpciones(null);
      }
      setError(null);
    } catch {
      if (requestId === requestRef.current) setError('No se pudieron cargar los grupos.');
    }
  }, []);
  // `version` changes when the page's "Actualizar" asks everything again.
  useEffect(() => {
    recargar();
  }, [recargar, version]);
  return { grupos, opciones, error, errorOpciones, recargar };
}
