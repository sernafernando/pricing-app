import { useEffect, useState } from 'react';
import api from '../services/api';
import { useDebounce } from './useDebounce';

function joinCsv(values) {
  return values.length > 0 ? values.join(',') : undefined;
}

function pruneSelected(selected, availableKeys) {
  const allowed = new Set(availableKeys.map(String));
  return selected.filter((key) => allowed.has(String(key)));
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
 * Prunes parent selections that fall outside the current universe.
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
  onMarcasChange,
  onSubcategoriasChange,
  onPmsChange,
  onTiposPublicacionChange,
  onPricelistsChange,
}) {
  const [opciones, setOpciones] = useState(EMPTY);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const eanDebounced = useDebounce(ean.trim(), 300);
  const catalogDebounced = useDebounce(catalogProductId.trim(), 300);

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
          },
        });
        if (cancelled) return;
        const next = {
          marcas: data.marcas || [],
          subcategorias: data.subcategorias || [],
          pms: data.pms || [],
          tipos_publicacion: data.tipos_publicacion || [],
          listas_precios: data.listas_precios || [],
        };
        setOpciones(next);

        const nextMarcas = pruneSelected(marcas, next.marcas);
        if (nextMarcas.length !== marcas.length) onMarcasChange(nextMarcas);

        const nextSubcats = pruneSelected(
          subcategorias,
          next.subcategorias.map((row) => row.id),
        );
        if (nextSubcats.length !== subcategorias.length) onSubcategoriasChange(nextSubcats);

        const nextPms = pruneSelected(
          pms,
          next.pms.map((row) => row.id),
        );
        if (nextPms.length !== pms.length) onPmsChange(nextPms);

        const nextTipos = pruneSelected(
          tiposPublicacion,
          next.tipos_publicacion.map((row) => row.id),
        );
        if (nextTipos.length !== tiposPublicacion.length) onTiposPublicacionChange(nextTipos);

        const nextLists = pruneSelected(
          pricelists,
          next.listas_precios.map((row) => row.id),
        );
        if (nextLists.length !== pricelists.length) onPricelistsChange(nextLists);
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
    // Parent setters are recreated each render — omit from deps on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    marcas,
    subcategorias,
    pms,
    tiposPublicacion,
    pricelists,
    tiendas,
    eanDebounced,
    catalogDebounced,
    reloadToken,
  ]);

  return {
    opciones,
    loading,
    loadError,
    retry: () => setReloadToken((n) => n + 1),
  };
}
