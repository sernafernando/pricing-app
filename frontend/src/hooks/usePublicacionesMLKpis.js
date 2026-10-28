import { publicacionesMlAPI } from '../services/api';
import { useViewRead } from './useViewRead';

const readKpis = (params, config) => publicacionesMlAPI.kpis(params, config);
const readStats = (params, config) => publicacionesMlAPI.stats(params, config);

/**
 * The KPI strip's data (publicaciones-ml-vista P12b): `GET /ml-publications/view/kpis` for `params`, asked again
 * only when they change (or on `reload`). It does not know the rows: a period change moves this request alone.
 * A request that is no longer the latest is aborted, and the last good figures stay while the next ones load.
 */
export function usePublicacionesMLKpis(params, enabled) {
  return useViewRead(readKpis, params, enabled);
}

/** Productos' stat cards (S12d4): `GET /ml-publications/view/stats` for `params`, read as the KPI strip is. */
export function usePublicationStats(params, enabled) {
  return useViewRead(readStats, params, enabled);
}
