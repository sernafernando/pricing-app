import { Search } from 'lucide-react';
import styles from '../../pages/TiendaNubeReconcile.module.css';
import { VERDICT_SUB_TABS } from './reconcileSubTabs';

// Search input + verdict-chip tablist. Extracted verbatim from
// `TiendaNubeReconcile.jsx` (structural extraction, PR-6 pattern) — the
// roving-focus/arrow-key behavior and `role="tablist"`/`aria-selected`
// semantics live in the page (keyboard handling is stateful behavior, not
// markup) and are wired in here via `tabRefs`/`onTabKeyDown`.
export default function ReconcileFilterBar({
  searchInput,
  onSearchChange,
  subTab,
  setSubTab,
  tabRefs,
  onTabKeyDown,
  totalTodos,
  verdictCounts,
  puedeGestionarBanlist,
  baneadosCount,
  tabPanelId,
}) {
  return (
    <div className={styles.filterBar}>
      <div className={styles.searchWrap}>
        <Search size={14} className={styles.searchIcon} aria-hidden="true" />
        <input
          type="search"
          className={styles.searchInput}
          placeholder="Buscar por EAN, título o SKU de TN"
          value={searchInput}
          onChange={onSearchChange}
          aria-label="Buscar por EAN, título o SKU de TN"
        />
      </div>
      <div
        className={styles.subTabBar}
        role="tablist"
        aria-label="Veredictos de reconciliación"
        onKeyDown={onTabKeyDown}
      >
        {VERDICT_SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            ref={(el) => {
              tabRefs.current[tab.id] = el;
            }}
            type="button"
            role="tab"
            id={`tn-tab-${tab.id}`}
            aria-selected={subTab === tab.id}
            aria-controls={tabPanelId}
            tabIndex={subTab === tab.id ? 0 : -1}
            className={`${styles.subTab} ${subTab === tab.id ? styles.subTabActive : ''}`}
            onClick={() => setSubTab(tab.id)}
          >
            {tab.label}{' '}
            <span className={styles.subTabCount}>
              ({tab.id === 'todos' ? totalTodos : verdictCounts[tab.id] || 0})
            </span>
          </button>
        ))}
        {puedeGestionarBanlist && (
          <button
            ref={(el) => {
              tabRefs.current.BANLIST = el;
            }}
            type="button"
            role="tab"
            id="tn-tab-BANLIST"
            aria-selected={subTab === 'BANLIST'}
            aria-controls={tabPanelId}
            tabIndex={subTab === 'BANLIST' ? 0 : -1}
            className={`${styles.subTab} ${subTab === 'BANLIST' ? styles.subTabActive : ''}`}
            onClick={() => setSubTab('BANLIST')}
          >
            Banlist <span className={styles.subTabCount}>({baneadosCount})</span>
          </button>
        )}
      </div>
    </div>
  );
}
