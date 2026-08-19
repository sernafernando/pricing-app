/**
 * CategorySection — category picker UI: top-N embedder suggestions as
 * radios (top-1 pre-selected) + a debounced NAME search against
 * `GET /categorias?q=`. Moved verbatim out of the pre-decomposition
 * `TnPublishModal.jsx`. Category selection is ALWAYS an object
 * `{ id, path }` (or null) — there is no numeric-id entry anywhere in this
 * form.
 */
import { Search, Check } from 'lucide-react';
import styles from './TnPublishModal.module.css';

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
}) {
  return (
    <div className={styles.section} data-testid="tn-publish-field-categories">
      <h3 className={styles.sectionTitle}>Categoría</h3>
      {loadingSuggestion ? (
        <p className={styles.fieldHint}>Buscando categoría sugerida...</p>
      ) : (
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
            {!searching && searchResults.length > 0 && (
              <ul className={styles.searchResults}>
                {searchResults.map((result) => (
                  <li key={result.tn_category_id}>
                    <button type="button" className={styles.searchResultBtn} onClick={() => pickSearchResult(result)}>
                      {result.category_path}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {!searching &&
              searchResults.length === 0 &&
              debouncedCategoryQuery.trim().length >= 2 &&
              !searchError && <p className={styles.fieldHint}>Sin resultados para esa búsqueda.</p>}
          </div>

          {selectedCategory != null ? (
            <p className={styles.selectedCategory}>
              <Check size={13} aria-hidden="true" />
              <span>
                Categoría seleccionada: <strong>{selectedCategory.path}</strong>
              </span>
            </p>
          ) : (
            <p className={styles.fieldHint}>Elegí una categoría sugerida o buscala por nombre para poder publicar.</p>
          )}
        </>
      )}
    </div>
  );
}
