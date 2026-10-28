import { useEffect, useState } from 'react';
import api from '../services/api';
import { useDebounce } from './useDebounce';

function joinCsv(values) {
  return values.length > 0 ? values.join(',') : undefined;
}

/**
 * Shared MLA queue + scope filter state for PARA GANAR Advisor/Criterios.
 */
export default function useParaGanarCola(pageSize = 50) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [qInput, setQInput] = useState('');
  const [marcas, setMarcas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [pms, setPms] = useState([]);
  const [tiposPublicacion, setTiposPublicacion] = useState([]);
  const [pricelists, setPricelists] = useState([]);
  const [tiendas, setTiendas] = useState([]);
  const [eanInput, setEanInput] = useState('');
  const [catalogInput, setCatalogInput] = useState('');
  const [costoUsdMinInput, setCostoUsdMinInput] = useState('');
  const [costoUsdMaxInput, setCostoUsdMaxInput] = useState('');
  const ean = useDebounce(eanInput.trim(), 300);
  const catalogProductId = useDebounce(catalogInput.trim(), 300);
  const costoUsdMin = useDebounce(costoUsdMinInput.trim(), 300);
  const costoUsdMax = useDebounce(costoUsdMaxInput.trim(), 300);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedMla, setSelectedMla] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get('/para-ganar/cola', {
          params: {
            page,
            page_size: pageSize,
            q: q || undefined,
            marcas: joinCsv(marcas),
            subcategorias: joinCsv(subcategorias),
            pms: joinCsv(pms),
            tipos_publicacion: joinCsv(tiposPublicacion),
            pricelists: joinCsv(pricelists),
            tiendas: joinCsv(tiendas),
            ean: ean || undefined,
            catalog_product_id: catalogProductId || undefined,
            ...(Number.isFinite(Number(costoUsdMin)) && costoUsdMin !== ''
              ? { costo_usd_min: Number(costoUsdMin) }
              : {}),
            ...(Number.isFinite(Number(costoUsdMax)) && costoUsdMax !== ''
              ? { costo_usd_max: Number(costoUsdMax) }
              : {}),
          },
        });
        if (cancelled) return;
        setItems(data.items || []);
        setTotal(data.total || 0);
        setSelectedMla((prev) => {
          if (!prev) return null;
          return (data.items || []).some((row) => row.mla === prev) ? prev : null;
        });
      } catch (err) {
        if (cancelled) return;
        if (err.response?.status === 403) {
          setError('No tenés permiso para ver esta sección (productos.ver).');
        } else {
          setError('No se pudo cargar la cola de publicaciones.');
        }
        setItems([]);
        setTotal(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [
    page,
    pageSize,
    q,
    marcas,
    subcategorias,
    pms,
    tiposPublicacion,
    pricelists,
    tiendas,
    ean,
    catalogProductId,
    costoUsdMin,
    costoUsdMax,
    reloadToken,
  ]);

  const resetPage = (setter) => (next) => {
    setPage(1);
    setter(next);
  };

  const clearAlcance = () => {
    setPage(1);
    setMarcas([]);
    setSubcategorias([]);
    setPms([]);
    setTiposPublicacion([]);
    setPricelists([]);
    setTiendas([]);
    setEanInput('');
    setCatalogInput('');
    setCostoUsdMinInput('');
    setCostoUsdMaxInput('');
  };

  const applySearch = (event) => {
    event.preventDefault();
    setPage(1);
    setQ(qInput.trim());
  };

  const selected = items.find((row) => row.mla === selectedMla) || null;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return {
    items,
    total,
    page,
    setPage,
    pageSize,
    qInput,
    setQInput,
    marcas,
    subcategorias,
    pms,
    tiposPublicacion,
    pricelists,
    tiendas,
    eanInput,
    catalogInput,
    costoUsdMinInput,
    costoUsdMaxInput,
    loading,
    error,
    selectedMla,
    setSelectedMla,
    selected,
    totalPages,
    applySearch,
    clearAlcance,
    setMarcas: resetPage(setMarcas),
    setSubcategorias: resetPage(setSubcategorias),
    setPms: resetPage(setPms),
    setTiposPublicacion: resetPage(setTiposPublicacion),
    setPricelists: resetPage(setPricelists),
    setTiendas: resetPage(setTiendas),
    setEanInput: resetPage(setEanInput),
    setCatalogInput: resetPage(setCatalogInput),
    setCostoUsdMinInput: resetPage(setCostoUsdMinInput),
    setCostoUsdMaxInput: resetPage(setCostoUsdMaxInput),
    reload: () => setReloadToken((n) => n + 1),
  };
}
