import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Filter, Package, PackageOpen } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import usePrearmadasArmadas from '../hooks/usePrearmadasArmadas';
import { useDebounce } from '../hooks/useDebounce';
import styles from './PrearmadasDisponibles.module.css';

const PERM = 'produccion.ver_prearmadas_stats';
// Max permitido por el endpoint. Como agrupamos por SKU client-side,
// pedimos el max para evitar que un solo SKU con muchas unidades
// llene una página entera y deje 0 cards visibles.
const PAGE_SIZE = 200;

// ── Helpers ──────────────────────────────────────────────────────────────────

function WindowsBadge({ value }) {
  if (!value) return <span className={`${styles.winBadge} ${styles.winNone}`}>Sin Windows</span>;
  if (value === 'home') return <span className={`${styles.winBadge} ${styles.winHome}`}>Home</span>;
  if (value === 'pro') return <span className={`${styles.winBadge} ${styles.winPro}`}>Pro</span>;
  return <span className={`${styles.winBadge} ${styles.winNone}`}>{value}</span>;
}

function CoverChip({ cover }) {
  const cls = cover.classification === 'exact' ? styles.coverExact : styles.coverUpgrade;
  return (
    <span className={`${styles.coverChip} ${cls}`} title={cover.item_desc || cover.item_code}>
      {cover.item_code}
    </span>
  );
}

function SkeletonCards({ count = 6 }) {
  return Array.from({ length: count }).map((_, i) => (
    <div key={i} className={styles.skeletonCard}>
      <div className={styles.skeletonLine} style={{ width: '70%' }} />
      <div className={styles.skeletonLine} style={{ width: '40%' }} />
      <div className={styles.skeletonLine} style={{ width: '90%' }} />
    </div>
  ));
}

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PrearmadasDisponibles() {
  const { tienePermiso } = usePermisos();

  const [searchInput, setSearchInput] = useState('');
  const [winFilter, setWinFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState({});

  const debouncedEanBase = useDebounce(searchInput, 300);

  const { items, total, loading, error, refetch } = usePrearmadasArmadas({
    eanBase: debouncedEanBase,
    page,
    pageSize: PAGE_SIZE,
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedEanBase]);

  // Client-side Windows filter (applied before grouping)
  const filteredItems = useMemo(() => {
    if (winFilter === 'all') return items;
    if (winFilter === 'none') return items.filter((it) => !it.incluye_windows);
    return items.filter((it) => it.incluye_windows === winFilter);
  }, [items, winFilter]);

  // Group by combo_item_code (SKU). Each group = 1 card.
  const groupedBySKU = useMemo(() => {
    const map = new Map();
    for (const item of filteredItems) {
      const key = item.combo_item_code;
      if (!map.has(key)) {
        map.set(key, {
          sku: item.combo_item_code,
          descripcion: item.combo_item_desc,
          parsed: item.parsed || {},
          incluye_windows: item.incluye_windows,
          covers: item.covers || [],
          units: [],
        });
      }
      map.get(key).units.push({
        prearmado_id: item.prearmado_id,
        codigo: item.codigo,
        created_at: item.created_at,
      });
    }
    // Sort by count desc, then by SKU
    return Array.from(map.values()).sort(
      (a, b) => b.units.length - a.units.length || a.sku.localeCompare(b.sku),
    );
  }, [filteredItems]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const toggleCard = (sku) => {
    setExpanded((prev) => ({ ...prev, [sku]: !prev[sku] }));
  };

  // ── No permission ──
  if (!tienePermiso(PERM)) {
    return (
      <div className={styles.noPerm}>
        <PackageOpen size={48} />
        <p>No tenés permiso para ver esta sección.</p>
        <small>
          Solicitá el permiso <code>{PERM}</code> a un administrador.
        </small>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <Package size={22} />
        <h1>Prearmadas disponibles</h1>
        {!loading && !error && (
          <span className={styles.totalsHint}>
            {total} unidad{total === 1 ? '' : 'es'} en {groupedBySKU.length} modelo
            {groupedBySKU.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {/* Filter bar */}
      <div className={styles.filterBar}>
        <Filter size={15} className={styles.filterIcon} />
        <input
          type="text"
          className={styles.searchInput}
          placeholder="Buscar por EAN base (ej: LENOVO)..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          aria-label="Filtrar por EAN base"
        />
        <select
          className={styles.filterSelect}
          value={winFilter}
          onChange={(e) => setWinFilter(e.target.value)}
          aria-label="Filtrar por variante Windows"
        >
          <option value="all">Todas las variantes</option>
          <option value="home">Windows Home</option>
          <option value="pro">Windows Pro</option>
          <option value="none">Sin Windows</option>
        </select>
      </div>

      {/* Error state */}
      {error && (
        <div className={styles.stateBox}>
          <PackageOpen size={36} />
          <span>Error al cargar las prearmadas. Intentá de nuevo.</span>
          <button className={styles.retryBtn} onClick={refetch}>
            Reintentar
          </button>
        </div>
      )}

      {/* Cards grid */}
      {!error && (
        <div className={styles.cardsGrid}>
          {loading && <SkeletonCards />}
          {!loading && groupedBySKU.length === 0 && (
            <div className={styles.stateBox}>
              <PackageOpen size={36} />
              <span>No hay prearmadas armadas con los filtros actuales.</span>
            </div>
          )}
          {!loading &&
            groupedBySKU.map((group) => (
              <SKUCard
                key={group.sku}
                group={group}
                isExpanded={!!expanded[group.sku]}
                onToggle={() => toggleCard(group.sku)}
              />
            ))}
        </div>
      )}

      {/* Pagination */}
      {!error && !loading && total > PAGE_SIZE && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            ← Anterior
          </button>
          <span>
            Página {page} de {totalPages} &nbsp;·&nbsp; {total} unidad{total === 1 ? '' : 'es'} en total
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Siguiente →
          </button>
        </div>
      )}
    </div>
  );
}

// ── Card sub-component ────────────────────────────────────────────────────────

function SKUCard({ group, isExpanded, onToggle }) {
  const { sku, descripcion, parsed, incluye_windows, covers, units } = group;
  const count = units.length;
  const hasUpgradeCovers = covers.some((c) => c.classification === 'upgrade');

  return (
    <div className={styles.card}>
      <header className={styles.cardHeader}>
        <div className={styles.cardTitleBlock}>
          <div className={styles.cardSku}>{sku}</div>
          {descripcion && <div className={styles.cardDesc}>{descripcion}</div>}
        </div>
        <div className={styles.cardCount} aria-label={`${count} ${count === 1 ? 'unidad lista' : 'unidades listas'}`}>
          <span className={styles.cardCountNum}>{count}</span>
          <span className={styles.cardCountLabel}>
            {count === 1 ? 'unidad' : 'unidades'}
          </span>
        </div>
      </header>

      <div className={styles.cardMeta}>
        <WindowsBadge value={incluye_windows} />
        {parsed.memoria && <span className={styles.metaPill}>{parsed.memoria} GB RAM</span>}
        {parsed.disco && <span className={styles.metaPill}>{parsed.disco}</span>}
      </div>

      {covers.length > 0 && (
        <div className={styles.cardCovers}>
          <span className={styles.cardCoversLabel}>
            Cubre {covers.length === 1 ? 'el SKU' : `${covers.length} SKUs`}
            {hasUpgradeCovers && ' (algunos con upgrade)'}:
          </span>
          <div className={styles.covers}>
            {covers.map((c) => (
              <CoverChip key={c.item_id} cover={c} />
            ))}
          </div>
        </div>
      )}

      <button
        type="button"
        className={styles.cardExpandBtn}
        onClick={onToggle}
        aria-expanded={isExpanded}
      >
        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {isExpanded
          ? count === 1
            ? 'Ocultar unidad'
            : 'Ocultar unidades individuales'
          : count === 1
            ? 'Ver la unidad'
            : `Ver las ${count} unidades`}
      </button>

      {isExpanded && (
        <ul className={styles.unitsList}>
          {units.map((u) => (
            <li key={u.prearmado_id} className={styles.unitRow}>
              <span className={styles.unitCodigo}>{u.codigo}</span>
              <span className={styles.unitFecha}>{formatDate(u.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
