import { useEffect, useState } from 'react';
import { parKey } from './parKey';
import styles from './ParesTable.module.css';

const DEBOUNCE_MS = 200;

/**
 * ParesTable — PURE presentational (marca, categoria) pair table
 * (sub-pm-bulk-assignment Slice 3).
 *
 * Owns NO data fetching and NO business logic: `pares`, the checked-pairs
 * Set, and every mutation are supplied by the parent. Checkbox state is a
 * plain `<input type="checkbox">` driven by a `Set` — mirrors the pattern in
 * TiendaNubeReconcile.jsx (baneadosSeleccionados), NOT TanStack row
 * selection: the parent already needs the same set arithmetic for the
 * grant/revoke diff, so this table must not duplicate it internally.
 *
 * Filter cardinality (measured in production, design D6/sizing):
 *   - marca: ~200 distinct values -> debounced, case-insensitive TEXT input
 *     (a select would be unusable at that width).
 *   - categoria: ~26 distinct values -> plain <select> with "Todas"
 *     (bounded, scannable as options).
 *
 * "Select all filtered" only ever affects what these two filters currently
 * show — worst case in production is 10 rows (LENOVO), so no confirmation
 * or scale guard is needed.
 *
 * Pairs with `usuario_id === null` (18 in production, admin-manageable
 * only) MUST render "Sin titular" muted, never a blank/null cell, and stay
 * selectable — they are real launch-day data, not a theoretical edge case.
 *
 * `checked` keys MUST be built with `parKey(marca, categoria)` from
 * `./parKey.js` — a plain `${marca}|${categoria}` template string collides
 * whenever a marca or categoria contains `|` (ERP-sourced, human-entered
 * data; not guaranteed pipe-free). The Slice 4 container MUST import and
 * reuse the same `parKey` helper rather than reinventing an incompatible
 * key scheme.
 */
export default function ParesTable({ pares, checked, onToggle, onSelectAllFiltered }) {
  const [filtroMarcaInput, setFiltroMarcaInput] = useState('');
  const [filtroMarca, setFiltroMarca] = useState('');
  const [filtroCategoria, setFiltroCategoria] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setFiltroMarca(filtroMarcaInput), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [filtroMarcaInput]);

  const categorias = [...new Set(pares.map((p) => p.categoria))].sort();

  const marcaBuscada = filtroMarca.trim().toLowerCase();
  const paresFiltrados = pares.filter((p) => {
    const coincideMarca = !marcaBuscada || p.marca.toLowerCase().includes(marcaBuscada);
    const coincideCategoria = !filtroCategoria || p.categoria === filtroCategoria;
    return coincideMarca && coincideCategoria;
  });

  const seleccionarTodoFiltrado = () => {
    onSelectAllFiltered(paresFiltrados.map(({ marca, categoria }) => ({ marca, categoria })));
  };

  return (
    <div>
      <div className={styles.filtros}>
        <div className={styles.filtroCampo}>
          <label className={styles.filtroLabel} htmlFor="paresTableFiltroMarca">
            Filtrar por marca
          </label>
          <input
            id="paresTableFiltroMarca"
            type="text"
            className={styles.filtroInput}
            value={filtroMarcaInput}
            onChange={(e) => setFiltroMarcaInput(e.target.value)}
            placeholder="Buscar marca..."
          />
        </div>
        <div className={styles.filtroCampo}>
          <label className={styles.filtroLabel} htmlFor="paresTableFiltroCategoria">
            Filtrar por categoría
          </label>
          <select
            id="paresTableFiltroCategoria"
            className={styles.filtroSelect}
            value={filtroCategoria}
            onChange={(e) => setFiltroCategoria(e.target.value)}
          >
            <option value="">Todas</option>
            {categorias.map((categoria) => (
              <option key={categoria} value={categoria}>{categoria}</option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="btn-tesla outline-subtle-primary sm"
          onClick={seleccionarTodoFiltrado}
          disabled={paresFiltrados.length === 0}
        >
          Seleccionar todo lo filtrado
        </button>
      </div>

      {paresFiltrados.length === 0 ? (
        <div className={styles.emptyState}>
          {pares.length === 0
            ? 'No hay pares marca/categoría disponibles todavía.'
            : 'Ningún par coincide con los filtros aplicados.'}
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th></th>
                <th>Marca</th>
                <th>Categoría</th>
                <th>Titular</th>
              </tr>
            </thead>
            <tbody>
              {paresFiltrados.map((par) => {
                const key = parKey(par.marca, par.categoria);
                return (
                  <tr key={key}>
                    <td>
                      <input
                        type="checkbox"
                        checked={checked.has(key)}
                        onChange={() => onToggle(par.marca, par.categoria)}
                        aria-label={`Seleccionar ${par.marca} / ${par.categoria}`}
                      />
                    </td>
                    <td>{par.marca}</td>
                    <td>{par.categoria}</td>
                    <td>
                      {par.usuario_id == null ? (
                        <span className={styles.sinTitular}>Sin titular</span>
                      ) : (
                        par.usuario_nombre || `Usuario #${par.usuario_id}`
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
