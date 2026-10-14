import { useEffect, useState } from 'react';
import { offsetsGananciaAPI } from '../services/api';
import { cargarOffsetsVigentes } from '../utils/offsetsGanancia';

/**
 * The current profit offsets (the ones Productos applies to its "markup con
 * offsets"), read only when `enabled`: undefined while they load, null when
 * they cannot be read, else `{ offsets, grupoFiltros, tipoCambio }` for
 * `costoConOffset` (utils/offsetsGanancia).
 */
export function useOffsetsVigentes(enabled) {
  const [contexto, setContexto] = useState(undefined);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    setContexto(undefined);
    cargarOffsetsVigentes({
      offsets: () => offsetsGananciaAPI.vigentes(),
      tipoCambio: () => offsetsGananciaAPI.tipoCambioHoy(),
      grupoFiltros: (id) => offsetsGananciaAPI.grupoFiltros(id),
    })
      .then((loaded) => active && setContexto(loaded))
      .catch(() => active && setContexto(null));
    return () => {
      active = false;
    };
  }, [enabled]);
  return enabled ? contexto : undefined;
}
