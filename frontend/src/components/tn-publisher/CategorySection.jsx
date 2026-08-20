/**
 * CategorySection — "Categoría" card (PR-9 design item b): a green
 * confirmation row when a category is selected (path + similarity + a
 * `Cambiar` link), plus the existing radiogroup suggestions + NAME search
 * picker. Category selection is ALWAYS an object `{ id, path }` (or null) —
 * there is no numeric-id entry anywhere in this form.
 *
 * Deliberate deviation from the literal design brief: the picker starts
 * EXPANDED (not hidden behind `Cambiar`) rather than collapsed, because the
 * existing test suite interacts with the radiogroup/search inputs directly
 * after the top-1 suggestion auto-preselects, with no prior click on
 * `Cambiar` — collapsing by default would turn "select the alternate
 * category" into a 2-step flow and break that interaction contract.
 * `Cambiar` still toggles collapse/expand; it just doesn't gate the
 * INITIAL render.
 */
import { useMemo, useState } from 'react';
import { Search, Check } from 'lucide-react';
import shellStyles from './TnPublisherShell.module.css';
import styles from './TnPublishModal.module.css';

/**
 * groupByTopBranch — defect A: a flat list of hundreds of browsed
 * categories hides the tree's structure. Groups by the FIRST `>`-separated
 * segment of `category_path` (e.g. "COMPUTACION", "HOGAR"), preserving the
 * server's alphabetical ordering within and across groups — never
 * re-sorted client-side, so the grouping is purely a presentation layer
 * over the same data.
 */
function groupByTopBranch(results) {
  const groups = [];
  const indexByBranch = new Map();
  for (const result of results) {
    const branch = (result.category_path.split('>')[0] || '').trim() || result.category_path;
    if (!indexByBranch.has(branch)) {
      indexByBranch.set(branch, groups.length);
      groups.push({ branch, items: [] });
    }
    groups[indexByBranch.get(branch)].items.push(result);
  }
  return groups;
}

export default function CategorySection({
  loadingSuggestion,
  suggestions,
  selectedCategory,
  setSelectedCategory,
  selectionOutsideSuggestions,
  categoryQuery,
  setCategoryQuery,
  debouncedCategoryQuery,
  searchResults,
  searching,
  searchError,
  pickSearchResult,
  catalogEmpty,
  catalogCapHit,
  syncingCategories,
  syncResult,
  syncError,
  syncCategories,
}) {
  const isBrowsing = debouncedCategoryQuery.trim().length === 0;
  const browsedGroups = useMemo(
    () => (isBrowsing ? groupByTopBranch(searchResults) : []),
    [isBrowsing, searchResults]
  );
  const [pickerExpanded, setPickerExpanded] = useState(true);
  const topSimilarity = suggestions.length > 0 ? Math.round(suggestions[0].similarity * 100) : null;

  return (
    <div className={shellStyles.card} data-testid="tn-publish-field-categories">
      <h3 className={shellStyles.cardTitle}>Categoría</h3>
      {loadingSuggestion ? (
        <p className={styles.fieldHint}>Buscando categoría sugerida...</p>
      ) : (
        <>
          {selectedCategory != null && (
            <p className={styles.selectedCategory}>
              <Check size={13} aria-hidden="true" />
              <span>
                Categoría seleccionada: <strong>{selectedCategory.path}</strong>
                {!selectionOutsideSuggestions && topSimilarity != null && (
                  <span className={styles.categorySimilarity}> ({topSimilarity}%)</span>
                )}
              </span>
              <button
                type="button"
                className={styles.searchResultBtn}
                onClick={() => setPickerExpanded((v) => !v)}
              >
                Cambiar
              </button>
            </p>
          )}

          {pickerExpanded && (
            <>
              {suggestions.length > 0 && (
                <div role="radiogroup" aria-label="Categoría TN sugerida" className={styles.categoryList}>
                  {suggestions.map((s, idx) => (
                    <label key={s.tn_category_id} className={styles.categoryOption}>
                      <input
                        type="radio"
                        name="tn-category"
                        checked={selectedCategory?.id === s.tn_category_id}
                        onChange={() => setSelectedCategory({ id: s.tn_category_id, path: s.category_path_text })}
                      />
                      <span className={idx === 0 ? styles.categoryTop : ''}>
                        {s.category_path_text}
                        <span className={styles.categorySimilarity}> ({Math.round(s.similarity * 100)}%)</span>
                      </span>
                    </label>
                  ))}
                  {selectionOutsideSuggestions && (
                    <label className={styles.categoryOption}>
                      <input type="radio" name="tn-category" checked readOnly />
                      <span className={styles.categoryTop}>{selectedCategory.path}</span>
                      <span className={styles.categoryPickedTag}>elegida por búsqueda</span>
                    </label>
                  )}
                </div>
              )}

              <div className={styles.categorySearchBlock}>
                <label className={styles.searchLabel} htmlFor="tn-category-search">
                  {suggestions.length > 0 ? 'Buscar otra categoría por nombre' : 'Buscar categoría por nombre'}
                </label>
                <div className={styles.searchInputWrap}>
                  <Search size={14} className={styles.searchIcon} aria-hidden="true" />
                  <input
                    id="tn-category-search"
                    type="search"
                    className={styles.searchInput}
                    value={categoryQuery}
                    placeholder="Ej.: Electrónica > Auriculares"
                    autoComplete="off"
                    onChange={(e) => setCategoryQuery(e.target.value)}
                  />
                </div>
                {searching && <p className={styles.fieldHint}>Buscando categorías...</p>}
                {searchError && <p className={styles.fieldError}>{searchError}</p>}
                {!searching && searchResults.length > 0 && isBrowsing && (
                  <div className={styles.categoryBrowseGroups}>
                    {browsedGroups.map((group) => (
                      <div key={group.branch}>
                        <p className={styles.categoryBranchHeading}>{group.branch}</p>
                        <ul className={styles.searchResults}>
                          {group.items.map((result) => (
                            <li key={result.tn_category_id}>
                              <button
                                type="button"
                                className={styles.searchResultBtn}
                                onClick={() => pickSearchResult(result)}
                              >
                                {result.category_path}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                    {catalogCapHit && (
                      <p className={styles.fieldHint} role="status">
                        El catálogo tiene más categorías de las que se pueden mostrar acá — no se muestran todas
                        las categorías. Escribí para buscar una específica.
                      </p>
                    )}
                  </div>
                )}
                {!searching && searchResults.length > 0 && !isBrowsing && (
                  <ul className={styles.searchResults}>
                    {searchResults.map((result) => (
                      <li key={result.tn_category_id}>
                        <button
                          type="button"
                          className={styles.searchResultBtn}
                          onClick={() => pickSearchResult(result)}
                        >
                          {result.category_path}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {/*
                  tn-categorias-descubribles fix (defect 1b/1c): an empty
                  CATALOG (nothing ever synced from Tienda Nube) and a query
                  with no MATCHES are different situations and must never
                  share the same message — the old copy blamed the
                  operator's search for what was actually an empty table.
                  `catalogEmpty` (derived from the unfiltered listing, see
                  `useCategoryPicker`) always wins over the plain
                  no-match copy, regardless of what's typed in the box.
                */}
                {!searching && searchResults.length === 0 && !searchError && catalogEmpty === true && (
                  <div className={styles.fieldHint} role="status">
                    <p>
                      Las categorías de Tienda Nube todavía no se sincronizaron — por eso no hay nada para
                      elegir acá.
                    </p>
                    <button
                      type="button"
                      className={styles.searchResultBtn}
                      onClick={syncCategories}
                      disabled={syncingCategories}
                    >
                      {syncingCategories ? 'Sincronizando categorías...' : 'Sincronizar categorías'}
                    </button>
                    {syncResult && !syncingCategories && (
                      <p>
                        {syncResult.skipped
                          ? `Sincronización omitida${syncResult.reason ? `: ${syncResult.reason}` : '.'}`
                          : `Se sincronizaron ${syncResult.synced} categorías.`}
                      </p>
                    )}
                    {syncError && !syncingCategories && <p className={styles.fieldError}>{syncError}</p>}
                  </div>
                )}
                {!searching &&
                  searchResults.length === 0 &&
                  !searchError &&
                  catalogEmpty !== true &&
                  debouncedCategoryQuery.trim().length >= 2 && (
                    <p className={styles.fieldHint}>Sin resultados para esa búsqueda.</p>
                  )}
              </div>
            </>
          )}

          {selectedCategory == null && (
            <p className={styles.fieldHint}>Elegí una categoría sugerida o buscala por nombre para poder publicar.</p>
          )}
          <p className={styles.fieldHint}>La categoría define el perfil de medidas que se sugiere arriba.</p>
        </>
      )}
    </div>
  );
}
