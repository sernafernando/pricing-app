import { useEffect, useState } from 'react';
import api from '../services/api';
import { useDebounce } from './useDebounce';

function joinCsv(values) {
  return values.length > 0 ? values.join(',') : undefined;
}

/** Keep selected keys visible even when the cascade universe no longer lists them. */
export function mergeStringOptions(available, selected) {
  const have = new Set((available || []).map(String));
  const orphans = (selected || []).map(String).filter((key) => key && !have.has(key));
  return orphans.length > 0 ? [...orphans, ...(available || [])] : available || [];
}

/** Same for `{ id, nombre }` facet rows (subcategoría, PM, tipo, lista). */
export function mergeRowOptions(available, selected) {
  const rows = available || [];
  const have = new Set(rows.map((row) => String(row.id)));
  const orphans = (selected || [])
    .filter((key) => key != null && key !== '' && !have.has(String(key)))
    .map((key) => ({ id: key, nombre: String(key) }));
  return orphans.length > 0 ? [...orphans, ...rows] : rows;
}

const EMPTY = {
  marcas: [],
  subcategorias: [],
  pms: [],
  tipos_publicacion: [],
  listas_precios: [],
};

/**
 * Loads cascading facet options for PARA GANAR scope filters.
 * Options shrink to the current universe; selections are never auto-cleared —
 * an incompatible combo keeps the chips and the cola shows zero rows.
 */
export default function useParaGanarAlcanceOpciones({
  marcas,
  subcategorias,
  pms,
  tiposPublicacion,
  pricelists,
  tiendas,
  ean,
  catalogProductId,
  costoUsdMin = '',
  costoUsdMax = '',
  incluirTradicionalSync = false,
  criteriosAplicados = null,
}) {
  const [opciones, setOpciones] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const eanDebounced = useDebounce(ean.trim(), 300);
  const catalogDebounced = useDebounce(catalogProductId.trim(), 300);
  const costoMinDebounced = useDebounce(String(costoUsdMin || '').trim(), 300);
  const costoMaxDebounced = useDebounce(String(costoUsdMax || '').trim(), 300);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setLoadError(null);
      try {
        const { data } = await api.get('/para-ganar/alcance-opciones', {
          params: {
            marcas: joinCsv(marcas),
            subcategorias: joinCsv(subcategorias),
            pms: joinCsv(pms),
            tipos_publicacion: joinCsv(tiposPublicacion),
            pricelists: joinCsv(pricelists),
            tiendas: joinCsv(tiendas),
            ean: eanDebounced || undefined,
            catalog_product_id: catalogDebounced || undefined,
            ...(Number.isFinite(Number(costoMinDebounced)) && costoMinDebounced !== ''
              ? { costo_usd_min: Number(costoMinDebounced) }
              : {}),
            ...(Number.isFinite(Number(costoMaxDebounced)) && costoMaxDebounced !== ''
              ? { costo_usd_max: Number(costoMaxDebounced) }
              : {}),
            ...(incluirTradicionalSync
              ? { incluir_tradicionales_sincronizadas: true }
              : {}),
            ...(criteriosAplicados === true || criteriosAplicados === false
              ? { criterios_aplicados: criteriosAplicados }
              : {}),
          },
        });
        if (cancelled) return;
        setOpciones({
          marcas: data.marcas || [],
          subcategorias: data.subcategorias || [],
          pms: data.pms || [],
          tipos_publicacion: data.tipos_publicacion || [],
          listas_precios: data.listas_precios || [],
        });
      } catch (err) {
        if (cancelled) return;
        setOpciones(EMPTY);
        if (err.response?.status === 403) {
          setLoadError('No tenés permiso para cargar filtros de alcance.');
        } else {
          setLoadError('No se pudieron cargar las opciones de alcance.');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [
    marcas,
    subcategorias,
    pms,
    tiposPublicacion,
    pricelists,
    tiendas,
    eanDebounced,
    catalogDebounced,
    costoMinDebounced,
    costoMaxDebounced,
    incluirTradicionalSync,
    criteriosAplicados,
    reloadToken,
  ]);

  return {
    opciones: {
      marcas: mergeStringOptions(opciones.marcas, marcas),
      subcategorias: mergeRowOptions(opciones.subcategorias, subcategorias),
      pms: mergeRowOptions(opciones.pms, pms),
      tipos_publicacion: mergeRowOptions(opciones.tipos_publicacion, tiposPublicacion),
      listas_precios: mergeRowOptions(opciones.listas_precios, pricelists),
    },
    loading,
    loadError,
    retry: () => setReloadToken((n) => n + 1),
  };
}
