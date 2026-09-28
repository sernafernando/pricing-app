import { useState, useEffect, useMemo, useCallback } from 'react';
import { productosAPI } from '../services/api';
import api from '../services/api';

const EMPTY_VALUE = { marcas: [], subcategorias: [], pms: [] };

/**
 * useProductFilters — self-contained state + data loading for the shared
 * product-filter trio (marca / subcategoría / PM).
 *
 * This hook is intentionally generic: it knows nothing about any specific
 * screen. It is controlled like a form field — the caller owns the
 * selection (`value`) and receives change requests through `onChange`, the
 * same shape any screen's own filter state (local or URL-backed) can
 * satisfy. `VentasML.jsx` is the first caller; the next screen wires it the
 * same way without touching this file.
 *
 * Behaviour ported from `Productos.jsx` / `useProductosFilters.js` on
 * purpose, not reinvented:
 *  - Options load once from `/marcas`, `/subcategorias`, `/usuarios/pms`.
 *  - Selecting one or more PMs narrows (never auto-selects) the marca and
 *    subcategoría options to only those PMs' own marcas/subcategorías,
 *    via `/pms/marcas` and `/pms/subcategorias` (`obtenerMarcasPorPMs` /
 *    `obtenerSubcategoriasPorPMs`).
 *  - A free-text search filters the marca/subcategoría lists client-side,
 *    on top of (not instead of) the PM narrowing.
 */
export function useProductFilters({ value = EMPTY_VALUE, onChange } = {}) {
  const selectedMarcas = value.marcas || [];
  const selectedSubcategorias = value.subcategorias || [];
  const selectedPms = value.pms || [];

  const [marcaOptions, setMarcaOptions] = useState([]);
  const [subcategoriaGroups, setSubcategoriaGroups] = useState([]); // [{categoria, subcategorias:[{id,nombre}]}]
  const [pmOptions, setPmOptions] = useState([]);

  const [marcasPorPM, setMarcasPorPM] = useState([]);
  const [subcategoriasPorPM, setSubcategoriasPorPM] = useState([]);

  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');

  // Options load once on mount — same as the initial PM/marcas/subcategorías
  // loaders in `useTiendaData.js` (no filter dependencies).
  useEffect(() => {
    let cancelled = false;
    productosAPI
      .marcas({})
      .then((res) => {
        if (!cancelled) setMarcaOptions(res.data?.marcas || []);
      })
      .catch(() => {
        if (!cancelled) setMarcaOptions([]);
      });
    productosAPI
      .subcategorias({})
      .then((res) => {
        if (!cancelled) setSubcategoriaGroups(res.data?.categorias || []);
      })
      .catch(() => {
        if (!cancelled) setSubcategoriaGroups([]);
      });
    api
      .get('/usuarios/pms', { params: { solo_con_marcas: true } })
      .then((res) => {
        if (!cancelled) setPmOptions(res.data || []);
      })
      .catch(() => {
        if (!cancelled) setPmOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pmKey = selectedPms.join(',');

  // Narrowing: when one or more PMs are selected, fetch the marcas and
  // subcategorías that belong to those PMs — same two endpoints
  // (`useTiendaData.js` `cargarDatosPorPM`), same all-or-nothing reset on
  // failure or on clearing the PM selection.
  useEffect(() => {
    let cancelled = false;
    if (selectedPms.length === 0) {
      setMarcasPorPM([]);
      setSubcategoriasPorPM([]);
      return () => {
        cancelled = true;
      };
    }
    Promise.all([
      productosAPI.obtenerMarcasPorPMs(pmKey),
      productosAPI.obtenerSubcategoriasPorPMs(pmKey),
    ])
      .then(([marcasRes, subcatsRes]) => {
        if (cancelled) return;
        setMarcasPorPM(marcasRes.data?.marcas || []);
        setSubcategoriasPorPM((subcatsRes.data?.subcategorias || []).map((s) => s.id));
      })
      .catch(() => {
        if (cancelled) return;
        setMarcasPorPM([]);
        setSubcategoriasPorPM([]);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pmKey]);

  const marcasFiltradas = useMemo(() => {
    return marcaOptions.filter((m) => {
      const matchBusqueda = m.toLowerCase().includes(busquedaMarca.toLowerCase());
      if (marcasPorPM.length > 0) return matchBusqueda && marcasPorPM.includes(m);
      return matchBusqueda;
    });
  }, [marcaOptions, busquedaMarca, marcasPorPM]);

  const subcategoriaGruposFiltrados = useMemo(() => {
    return (subcategoriaGroups || [])
      .map((grupo) => {
        const subs = (grupo.subcategorias || []).filter((sub) => {
          const matchBusqueda = sub.nombre
            .toLowerCase()
            .includes(busquedaSubcategoria.toLowerCase());
          if (subcategoriasPorPM.length > 0) return matchBusqueda && subcategoriasPorPM.includes(sub.id);
          return matchBusqueda;
        });
        return { ...grupo, subcategorias: subs };
      })
      .filter((grupo) => grupo.subcategorias.length > 0);
  }, [subcategoriaGroups, busquedaSubcategoria, subcategoriasPorPM]);

  const emit = useCallback(
    (next) => {
      onChange?.({
        marcas: next.marcas ?? selectedMarcas,
        subcategorias: next.subcategorias ?? selectedSubcategorias,
        pms: next.pms ?? selectedPms,
      });
    },
    [onChange, selectedMarcas, selectedSubcategorias, selectedPms],
  );

  const toggleMarca = useCallback(
    (marca) => {
      const next = selectedMarcas.includes(marca)
        ? selectedMarcas.filter((m) => m !== marca)
        : [...selectedMarcas, marca];
      emit({ marcas: next });
    },
    [selectedMarcas, emit],
  );

  const toggleSubcategoria = useCallback(
    (id) => {
      const next = selectedSubcategorias.includes(id)
        ? selectedSubcategorias.filter((s) => s !== id)
        : [...selectedSubcategorias, id];
      emit({ subcategorias: next });
    },
    [selectedSubcategorias, emit],
  );

  const togglePm = useCallback(
    (id) => {
      const next = selectedPms.includes(id)
        ? selectedPms.filter((p) => p !== id)
        : [...selectedPms, id];
      emit({ pms: next });
    },
    [selectedPms, emit],
  );




  return {
    selectedMarcas,
    selectedSubcategorias,
    selectedPms,
    marcasFiltradas,
    subcategoriaGruposFiltrados,
    pmOptions,
    busquedaMarca,
    setBusquedaMarca,
    busquedaSubcategoria,
    setBusquedaSubcategoria,
    toggleMarca,
    toggleSubcategoria,
    togglePm,
  };
}
