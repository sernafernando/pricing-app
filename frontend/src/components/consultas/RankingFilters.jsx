import { Filter } from 'lucide-react';
import styles from './RankingFilters.module.css';

const VENTANA_OPTIONS = [30, 60, 90, 180];

// Shown when the facets call fails or returns an empty depositos list,
// so the user always sees at least the default depot and can filter by it.
const FALLBACK_DEPOSITOS = [{ id: 1, label: 'Depósito 1' }];

/**
 * Filter bar for the ConsultasRanking page.
 * All values are controlled from outside (useConsultasRanking hook).
 * Dropdown options come from the facets endpoint via the page.
 */
export default function RankingFilters({
  marca,
  onMarcaChange,
  categoria,
  onCategoriaChange,
  pm,
  onPmChange,
  storIds,
  onStorIdsChange,
  ventanaDias,
  onVentanaDiasChange,
  facets,
  facetsLoading,
}) {
  const { marcas = [], categorias = [], pms = [], depositos: rawDepositos = [] } = facets ?? {};
  const depositos = rawDepositos.length > 0 ? rawDepositos : FALLBACK_DEPOSITOS;

  function handleDepotToggle(depotId) {
    if (storIds.includes(depotId)) {
      // Keep at least one selected
      if (storIds.length === 1) return;
      onStorIdsChange(storIds.filter((id) => id !== depotId));
    } else {
      onStorIdsChange([...storIds, depotId].sort((a, b) => a - b));
    }
  }

  return (
    <div className={styles.container}>
      <div className={styles.filterIcon}>
        <Filter size={16} />
      </div>

      {/* Marca — searchable via native datalist (191 options) */}
      <div className={styles.filterGroup}>
        <label className={styles.label} htmlFor="filter-marca">
          Marca
        </label>
        <input
          id="filter-marca"
          type="text"
          list="datalist-marcas"
          className={styles.input}
          placeholder="Todas"
          value={marca}
          onChange={(e) => onMarcaChange(e.target.value)}
          disabled={facetsLoading}
          autoComplete="off"
        />
        <datalist id="datalist-marcas">
          {marcas.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </div>

      {/* Categoría */}
      <div className={styles.filterGroup}>
        <label className={styles.label} htmlFor="filter-categoria">
          Categoría
        </label>
        <select
          id="filter-categoria"
          className={styles.select}
          value={categoria}
          onChange={(e) => onCategoriaChange(e.target.value)}
          disabled={facetsLoading}
        >
          <option value="">Todas</option>
          {categorias.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {/* PM */}
      <div className={styles.filterGroup}>
        <label className={styles.label} htmlFor="filter-pm">
          PM
        </label>
        <select
          id="filter-pm"
          className={styles.select}
          value={pm}
          onChange={(e) => onPmChange(e.target.value)}
          disabled={facetsLoading}
        >
          <option value="">Todos</option>
          {pms.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
          <option value="sin_pm">Sin PM</option>
        </select>
      </div>

      {/* Ventana de días */}
      <div className={styles.filterGroup}>
        <label className={styles.label} htmlFor="filter-ventana">
          Ventana ventas
        </label>
        <select
          id="filter-ventana"
          className={styles.select}
          value={ventanaDias}
          onChange={(e) => onVentanaDiasChange(Number(e.target.value))}
        >
          {VENTANA_OPTIONS.map((d) => (
            <option key={d} value={d}>
              {d} días
            </option>
          ))}
        </select>
      </div>

      {/* Depósitos — from facets; falls back to FALLBACK_DEPOSITOS if facets fail or return empty */}
      <div className={styles.filterGroup}>
        <span className={styles.label}>Depósitos</span>
        <div className={styles.depotGroup}>
          {depositos.map((depot) => {
            const active = storIds.includes(depot.id);
            return (
              <button
                key={depot.id}
                type="button"
                className={active ? styles.depotBtnActive : styles.depotBtn}
                onClick={() => handleDepotToggle(depot.id)}
                aria-pressed={active}
                aria-label={depot.label}
                title={depot.label}
              >
                {depot.id}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
