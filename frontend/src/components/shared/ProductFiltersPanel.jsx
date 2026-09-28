import { useState } from 'react';
import { useProductFilters } from '../../hooks/useProductFilters';

/**
 * ProductFiltersPanel — the shared marca/subcategoría/PM filter trio.
 *
 * Self-contained on purpose (see `odd/tasks/ventas-ml-filtros-producto.md`):
 * it owns its own option loading and PM-narrowing through
 * `useProductFilters`, and exposes a plain controlled-value contract
 * (`value` / `onChange`) with no knowledge of any specific screen. Ventas ML
 * is the first caller; the next screen (Productos, Rentabilidad,
 * TiendaNube) wires it the same way, without touching this file.
 *
 * Reuses the existing global filter classes (`filter-button`,
 * `advanced-filters-panel`, `dropdown-item`, ...) that `Productos.jsx`
 * already relies on, so no new styling surface is introduced.
 *
 * @param {Object} props
 * @param {{marcas: string[], subcategorias: number[], pms: number[]}} props.value
 * @param {(next: {marcas: string[], subcategorias: number[], pms: number[]}) => void} props.onChange
 */
export default function ProductFiltersPanel({ value, onChange }) {
  const [panelAbierto, setPanelAbierto] = useState(null); // 'marcas' | 'subcategorias' | 'pms' | null

  const {
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
  } = useProductFilters({ value, onChange });

  const togglePanel = (panel) => setPanelAbierto((prev) => (prev === panel ? null : panel));

  return (
    <div className="product-filters-panel">
      <div className="filter-buttons-row">
        <button
          type="button"
          className={`filter-button ${selectedMarcas.length > 0 ? 'active' : ''}`}
          onClick={() => togglePanel('marcas')}
        >
          Marca
          {selectedMarcas.length > 0 && (
            <span className="filter-badge">{selectedMarcas.length}</span>
          )}
        </button>

        <button
          type="button"
          className={`filter-button ${selectedSubcategorias.length > 0 ? 'active' : ''}`}
          onClick={() => togglePanel('subcategorias')}
        >
          Subcategoría
          {selectedSubcategorias.length > 0 && (
            <span className="filter-badge">{selectedSubcategorias.length}</span>
          )}
        </button>

        <button
          type="button"
          className={`filter-button ${selectedPms.length > 0 ? 'active' : ''}`}
          onClick={() => togglePanel('pms')}
        >
          PM
          {selectedPms.length > 0 && <span className="filter-badge">{selectedPms.length}</span>}
        </button>
      </div>

      {panelAbierto && (
        <div className="advanced-filters-panel">
          {panelAbierto === 'marcas' && (
            <>
              <div className="advanced-filters-header">
                <h3>Marcas</h3>
                {selectedMarcas.length > 0 && (
                  <button
                    onClick={() => onChange({ ...value, marcas: [] })}
                    className="btn-tesla outline-subtle-danger sm"
                  >
                    Limpiar filtros ({selectedMarcas.length})
                  </button>
                )}
              </div>
              <div className="dropdown-header">
                <div className="dropdown-search">
                  <input
                    type="text"
                    placeholder="Buscar marca..."
                    value={busquedaMarca}
                    onChange={(e) => setBusquedaMarca(e.target.value)}
                  />
                </div>
              </div>
              <div className="dropdown-content">
                {marcasFiltradas.map((marca) => (
                  <label
                    key={marca}
                    className={`dropdown-item ${selectedMarcas.includes(marca) ? 'selected' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedMarcas.includes(marca)}
                      onChange={() => toggleMarca(marca)}
                    />
                    <span>{marca}</span>
                  </label>
                ))}
              </div>
            </>
          )}

          {panelAbierto === 'subcategorias' && (
            <>
              <div className="advanced-filters-header">
                <h3>Subcategorías</h3>
                {selectedSubcategorias.length > 0 && (
                  <button
                    onClick={() => onChange({ ...value, subcategorias: [] })}
                    className="btn-tesla outline-subtle-danger sm"
                  >
                    Limpiar filtros ({selectedSubcategorias.length})
                  </button>
                )}
              </div>
              <div className="dropdown-header">
                <div className="dropdown-search">
                  <input
                    type="text"
                    placeholder="Buscar subcategoría..."
                    value={busquedaSubcategoria}
                    onChange={(e) => setBusquedaSubcategoria(e.target.value)}
                  />
                </div>
              </div>
              <div className="dropdown-content">
                {subcategoriaGruposFiltrados.map((grupo) => (
                  <div key={grupo.categoria}>
                    <div className="dropdown-group-label">{grupo.categoria}</div>
                    {grupo.subcategorias.map((sub) => (
                      <label
                        key={sub.id}
                        className={`dropdown-item ${
                          selectedSubcategorias.includes(sub.id) ? 'selected' : ''
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
              <div className="advanced-filters-header">
                <h3>Product Managers</h3>
                {selectedPms.length > 0 && (
                  <button
                    onClick={() => onChange({ ...value, pms: [] })}
                    className="btn-tesla outline-subtle-danger sm"
                  >
                    Limpiar filtros ({selectedPms.length})
                  </button>
                )}
              </div>
              <div className="dropdown-content">
                {pmOptions.map((pm) => (
                  <label
                    key={pm.id}
                    className={`dropdown-item ${selectedPms.includes(pm.id) ? 'selected' : ''}`}
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
