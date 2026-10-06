import { useState, useMemo, useCallback } from 'react';

// Stable references: a fresh `[]` per render would defeat the memoised lists below.
const NONE = [];
const EMPTY_VALUE = { marcas: [], categorias: [], subcategorias: [], pms: [] };
const EMPTY_OPTIONS = { marcas: [], categorias: [], subcategorias: [], pms: [] };

// Same normalisation as the server (`product_facets._upper`): trimmed, case-insensitive.
const norm = (text) => text.trim().toLowerCase();
const sameText = (a, b) => norm(a) === norm(b);
const hasText = (list, item) => list.some((x) => sameText(x, item));

const includesText = (text, needle) => text.toLowerCase().includes(needle.toLowerCase());

/**
 * useProductFilters — selection + search state for the shared product-filter
 * set (marca / categoría / subcategoría / PM).
 *
 * Controlled like a form field: the caller owns the selection (`value`) and
 * receives change requests through `onChange`. The OPTIONS are not loaded
 * here any more: each screen's own response carries them, already
 * cross-filtered by the server (`facets.product`: every other active filter
 * narrows each list, never its own), so the lists shrink and grow as the
 * operator picks (`metricas-ml-filtros-dinamicos`). This hook only
 *  - keeps a selected value visible even when the other filters rule it out
 *    or the lists have not arrived / failed to load (so it can be unticked):
 *    marca and categoría compare case-insensitively and the SERVER spelling
 *    is the canonical one (a selection spelled differently shows once,
 *    checked); a subcategoría or PM with no name on hand shows as
 *    `Subcategoría #id` / `PM #id`, and
 *  - filters the lists by the typed search, client-side.
 *
 * @param {{value?: object, onChange?: Function, options?: object}} [args]
 *   `options`: `{marcas: string[], categorias: string[],
 *   subcategorias: [{nombre, subcategorias: [{id, nombre}]}],
 *   pms: [{id, nombre}]}`
 */
export function useProductFilters({ value = EMPTY_VALUE, onChange, options } = {}) {
  const selectedMarcas = value.marcas ?? NONE;
  const selectedCategorias = value.categorias ?? NONE;
  const selectedSubcategorias = value.subcategorias ?? NONE;
  const selectedPms = value.pms ?? NONE;
  const offered = options ?? EMPTY_OPTIONS;

  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [busquedaCategoria, setBusquedaCategoria] = useState('');
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');

  const marcasFiltradas = useMemo(() => {
    const listed = offered.marcas ?? NONE;
    const all = [...listed, ...selectedMarcas.filter((m) => !hasText(listed, m))];
    return all.filter((m) => includesText(m, busquedaMarca));
  }, [offered.marcas, selectedMarcas, busquedaMarca]);

  const categoriasFiltradas = useMemo(() => {
    const listed = offered.categorias ?? NONE;
    const all = [...listed, ...selectedCategorias.filter((c) => !hasText(listed, c))];
    return all.filter((c) => includesText(c, busquedaCategoria));
  }, [offered.categorias, selectedCategorias, busquedaCategoria]);

  const subcategoriaGruposFiltrados = useMemo(() => {
    const groups = offered.subcategorias ?? NONE;
    const listedIds = new Set(groups.flatMap((g) => (g.subcategorias || []).map((sub) => sub.id)));
    const missing = selectedSubcategorias
      .filter((id) => !listedIds.has(id))
      .map((id) => ({ id, nombre: `Subcategoría #${id}` }));
    const all = missing.length > 0 ? [...groups, { nombre: 'Seleccionadas', subcategorias: missing }] : groups;
    return all
      .map((grupo) => ({
        ...grupo,
        subcategorias: (grupo.subcategorias || []).filter((sub) => includesText(sub.nombre, busquedaSubcategoria)),
      }))
      .filter((grupo) => grupo.subcategorias.length > 0);
  }, [offered.subcategorias, selectedSubcategorias, busquedaSubcategoria]);

  const pmOptions = useMemo(() => {
    const listed = offered.pms ?? NONE;
    const missing = selectedPms
      .filter((id) => !listed.some((pm) => pm.id === id))
      .map((id) => ({ id, nombre: `PM #${id}` }));
    return missing.length > 0 ? [...listed, ...missing] : listed;
  }, [offered.pms, selectedPms]);

  const emit = useCallback(
    (next) => {
      onChange?.({
        marcas: next.marcas ?? selectedMarcas,
        categorias: next.categorias ?? selectedCategorias,
        subcategorias: next.subcategorias ?? selectedSubcategorias,
        pms: next.pms ?? selectedPms,
      });
    },
    [onChange, selectedMarcas, selectedCategorias, selectedSubcategorias, selectedPms],
  );

  const toggleIn = (list, item) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  // Text lists compare case-insensitively: the checkbox shows the server spelling, the
  // selection may hold another (URL, older state), and either one must untick it.
  const toggleText = (list, item) =>
    hasText(list, item) ? list.filter((x) => !sameText(x, item)) : [...list, item];

  const toggleMarca = useCallback((marca) => emit({ marcas: toggleText(selectedMarcas, marca) }), [selectedMarcas, emit]);
  const toggleCategoria = useCallback(
    (categoria) => emit({ categorias: toggleText(selectedCategorias, categoria) }),
    [selectedCategorias, emit],
  );
  const isMarcaSelected = useCallback((marca) => hasText(selectedMarcas, marca), [selectedMarcas]);
  const isCategoriaSelected = useCallback((categoria) => hasText(selectedCategorias, categoria), [selectedCategorias]);
  const toggleSubcategoria = useCallback(
    (id) => emit({ subcategorias: toggleIn(selectedSubcategorias, id) }),
    [selectedSubcategorias, emit],
  );
  const togglePm = useCallback((id) => emit({ pms: toggleIn(selectedPms, id) }), [selectedPms, emit]);

  return {
    selectedMarcas,
    selectedCategorias,
    selectedSubcategorias,
    selectedPms,
    marcasFiltradas,
    categoriasFiltradas,
    subcategoriaGruposFiltrados,
    pmOptions,
    busquedaMarca,
    setBusquedaMarca,
    busquedaCategoria,
    setBusquedaCategoria,
    busquedaSubcategoria,
    setBusquedaSubcategoria,
    isMarcaSelected,
    isCategoriaSelected,
    toggleMarca,
    toggleCategoria,
    toggleSubcategoria,
    togglePm,
  };
}
