import { useState, useEffect, useRef } from 'react';
import { useProductFilters } from '../../hooks/useProductFilters';
import styles from './ProductFiltersPanel.module.css';

/**
 * ProductFiltersPanel — the shared marca / categoría / subcategoría / PM
 * filter set.
 *
 * A plain controlled-value contract (`value` / `onChange`) with no knowledge
 * of any specific screen. The OPTIONS come from the screen's own response
 * (`options` = its `facets.product`), already cross-filtered by the server:
 * every other active filter (and the store) narrows each list, never its own,
 * so picking a brand only offers its categories, subcategories and PMs, and
 * picking a PM only offers its brands, and so on (ODD
 * `metricas-ml-filtros-dinamicos`). Ventas ML and Métricas ML wire it the
 * same way (see `odd/tasks/ventas-ml-filtros-producto.md` for the origin).
 *
 * Styled entirely through `ProductFiltersPanel.module.css`, not by reusing
 * any page's global CSS: `.filter-button`, `.advanced-filters-panel`,
 * `.dropdown-*` and friends only exist today in `pages/Productos.css`,
 * `Tienda.css` and `ItemsSinMLA.css` — each loaded lazily with its own
 * page. A caller that isn't one of those three pages (Ventas ML included)
 * would render this component unstyled. The module CSS mirrors the visual
 * language `Productos.jsx` uses, built on `styles/theme.css` tokens instead
 * of that file's dark-only hardcoded colors, so it also works in light
 * mode regardless of navigation history.
 *
 * @param {Object} props
 * @param {{marcas: string[], categorias: string[], subcategorias: number[], pms: number[]}} props.value
 * @param {(next: {marcas: string[], categorias: string[], subcategorias: number[], pms: number[]}) => void} props.onChange
 * @param {{marcas: string[], categorias: string[], subcategorias: object[], pms: object[]}} [props.options]
 *   The cross-filtered lists; empty until the screen's first response.
 */
export default function ProductFiltersPanel({ value, onChange, options }) {
  const [panelAbierto, setPanelAbierto] = useState(null); // 'marcas' | 'categorias' | 'subcategorias' | 'pms' | null
  const containerRef = useRef(null);

  const {
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
  } = useProductFilters({ value, onChange, options });

  const togglePanel = (panel) => setPanelAbierto((prev) => (prev === panel ? null : panel));

  // Close on outside click while a dropdown is open — added/removed with
  // `panelAbierto` since it only matters then.
  useEffect(() => {
    if (!panelAbierto) return undefined;
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setPanelAbierto(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [panelAbierto]);

  // Escape closes the open dropdown. This is a shared component with no
  // knowledge of its host screen, but on Ventas ML it renders as a CHILD of
  // `VentasMLLayout`, which owns its OWN `window` Escape handler (clearing
  // the selected sale's detail panel) — see that component's docstring.
  // Two things make the two handlers not step on each other:
  //  - `preventDefault()` is the exact signal `VentasMLLayout` already
  //    checks (`if (e.defaultPrevented) return;`) before acting on its own
  //    Escape, so calling it here when THIS dropdown was open is enough to
  //    stop it from also clearing the selection on the same keypress.
  //  - That only works if this listener runs BEFORE `VentasMLLayout`'s —
  //    same-target (`window`) listeners fire in registration order, not
  //    tree order. Registering this listener ONCE on mount (not re-added
  //    every time the dropdown opens/closes) keeps it first: React commits
  //    child effects before parent effects, so this component (a child of
  //    `VentasMLLayout`) always mounts its listener before `VentasMLLayout`
  //    mounts its own — which only happens later, when a row gets
  //    selected — regardless of dropdown open/close churn afterwards.
  const panelAbiertoRef = useRef(panelAbierto);
  panelAbiertoRef.current = panelAbierto;
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape' || !panelAbiertoRef.current) return;
      e.preventDefault();
      setPanelAbierto(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <div className={styles.panel} ref={containerRef}>
      <div className={styles.buttonsRow}>
        <button
          type="button"
          className={`${styles.filterButton} ${selectedMarcas.length > 0 ? styles.filterButtonActive : ''}`}
          onClick={() => togglePanel('marcas')}
        >
          Marca
          {selectedMarcas.length > 0 && (
            <span className={styles.filterBadge}>{selectedMarcas.length}</span>
          )}
        </button>

        <button
          type="button"
          className={`${styles.filterButton} ${selectedCategorias.length > 0 ? styles.filterButtonActive : ''}`}
          onClick={() => togglePanel('categorias')}
        >
          Categoría
          {selectedCategorias.length > 0 && (
            <span className={styles.filterBadge}>{selectedCategorias.length}</span>
          )}
        </button>

        <button
          type="button"
          className={`${styles.filterButton} ${selectedSubcategorias.length > 0 ? styles.filterButtonActive : ''}`}
          onClick={() => togglePanel('subcategorias')}
        >
          Subcategoría
          {selectedSubcategorias.length > 0 && (
            <span className={styles.filterBadge}>{selectedSubcategorias.length}</span>
          )}
        </button>

        <button
          type="button"
          className={`${styles.filterButton} ${selectedPms.length > 0 ? styles.filterButtonActive : ''}`}
          onClick={() => togglePanel('pms')}
        >
          PM
          {selectedPms.length > 0 && <span className={styles.filterBadge}>{selectedPms.length}</span>}
        </button>
      </div>

      {panelAbierto && (
        <div className={styles.dropdown}>
          {panelAbierto === 'marcas' && (
            <>
              <div className={styles.dropdownHeaderRow}>
                <h3>Marcas</h3>
                {selectedMarcas.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange({ ...value, marcas: [] })}
                    className={styles.clearButton}
                  >
                    Limpiar filtros ({selectedMarcas.length})
                  </button>
                )}
              </div>
              <div className={styles.searchWrap}>
                <input
                  type="text"
                  placeholder="Buscar marca..."
                  value={busquedaMarca}
                  onChange={(e) => setBusquedaMarca(e.target.value)}
                />
              </div>
              <div className={styles.content}>
                {marcasFiltradas.map((marca) => (
                  <label
                    key={marca}
                    className={`${styles.item} ${isMarcaSelected(marca) ? styles.itemSelected : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={isMarcaSelected(marca)}
                      onChange={() => toggleMarca(marca)}
                    />
                    <span>{marca}</span>
                  </label>
                ))}
              </div>
            </>
          )}

          {panelAbierto === 'categorias' && (
            <>
              <div className={styles.dropdownHeaderRow}>
                <h3>Categorías</h3>
                {selectedCategorias.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange({ ...value, categorias: [] })}
                    className={styles.clearButton}
                  >
                    Limpiar filtros ({selectedCategorias.length})
                  </button>
                )}
              </div>
              <div className={styles.searchWrap}>
                <input
                  type="text"
                  placeholder="Buscar categoría..."
                  value={busquedaCategoria}
                  onChange={(e) => setBusquedaCategoria(e.target.value)}
                />
              </div>
              <div className={styles.content}>
                {categoriasFiltradas.map((categoria) => (
                  <label
                    key={categoria}
                    className={`${styles.item} ${isCategoriaSelected(categoria) ? styles.itemSelected : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={isCategoriaSelected(categoria)}
                      onChange={() => toggleCategoria(categoria)}
                    />
                    <span>{categoria}</span>
                  </label>
                ))}
              </div>
            </>
          )}

          {panelAbierto === 'subcategorias' && (
            <>
              <div className={styles.dropdownHeaderRow}>
                <h3>Subcategorías</h3>
                {selectedSubcategorias.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange({ ...value, subcategorias: [] })}
                    className={styles.clearButton}
                  >
                    Limpiar filtros ({selectedSubcategorias.length})
                  </button>
                )}
              </div>
              <div className={styles.searchWrap}>
                <input
                  type="text"
                  placeholder="Buscar subcategoría..."
                  value={busquedaSubcategoria}
                  onChange={(e) => setBusquedaSubcategoria(e.target.value)}
                />
              </div>
              <div className={styles.content}>
                {subcategoriaGruposFiltrados.map((grupo) => (
                  <div key={grupo.categoria}>
                    <div className={styles.groupLabel}>{grupo.categoria}</div>
                    {grupo.subcategorias.map((sub) => (
                      <label
                        key={sub.id}
                        className={`${styles.item} ${
                          selectedSubcategorias.includes(sub.id) ? styles.itemSelected : ''
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selectedSubcategorias.includes(sub.id)}
                          onChange={() => toggleSubcategoria(sub.id)}
                        />
                        <span>{sub.nombre}</span>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            </>
          )}

          {panelAbierto === 'pms' && (
            <>
              <div className={styles.dropdownHeaderRow}>
                <h3>Product Managers</h3>
                {selectedPms.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange({ ...value, pms: [] })}
                    className={styles.clearButton}
                  >
                    Limpiar filtros ({selectedPms.length})
                  </button>
                )}
              </div>
              <div className={styles.content}>
                {pmOptions.map((pm) => (
                  <label
                    key={pm.id}
                    className={`${styles.item} ${selectedPms.includes(pm.id) ? styles.itemSelected : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedPms.includes(pm.id)}
                      onChange={() => togglePm(pm.id)}
                    />
                    <span>{pm.nombre}</span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
