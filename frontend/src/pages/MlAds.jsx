/**
 * MlAds — the "ML Ads" page (ml-ads-cupones-display S8): Mercado Libre advertising in tabs. Aportes is the brand
 * contributions page, unchanged; Display is the account-level Display campaigns. The page keeps the old
 * `/ml-ads-aportes` URL, which opens Aportes; the active tab lives in `?tab=` so a link opens it directly.
 *
 * Accessible tabs: a `role="tablist"` with arrow-key navigation; only the active tab's content is rendered, in the
 * one always-present tab panel.
 *
 * Header and tabs follow the approved Stitch screen 56a8ea4c: one card with the title, the active tab's controls on
 * the right (`headerSlot`, where Display puts its range and Actualizar) and the tab bar. The Display tab shows how
 * many campaigns are active once Display reported them; the number stays while another tab is open.
 */
import { useCallback, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import AportesAdsML from './AportesAdsML';
import DisplayAdsML from './DisplayAdsML';
import { registrarPagina } from '../registry/tabRegistry';
import styles from './MlAds.module.css';

const TABS = [
  { key: 'aportes', label: 'Aportes', Component: AportesAdsML },
  { key: 'display', label: 'Display', Component: DisplayAdsML },
];
const PANEL_ID = 'ml-ads-panel';

// No tabs in the registry: registered tabs are offered for an operator PIN, which this page does not apply.
registrarPagina({ pagePath: '/ml-ads-aportes', pageLabel: 'ML Ads', tabs: [] });

export default function MlAds() {
  const [params, setParams] = useSearchParams();
  const active = TABS.find((t) => t.key === params.get('tab')) ?? TABS[0];
  const buttons = useRef({});
  const [headerSlot, setHeaderSlot] = useState(null);
  const [activeDisplay, setActiveDisplay] = useState(null);
  const onActiveCount = useCallback((n) => setActiveDisplay(n), []);

  const select = (key) => {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (key === TABS[0].key) next.delete('tab');
        else next.set('tab', key);
        return next;
      },
      { replace: true },
    );
  };

  const onKeyDown = (event) => {
    const index = TABS.indexOf(active);
    const moves = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: TABS.length - 1 };
    if (!(event.key in moves)) return;
    event.preventDefault();
    const next = TABS[(moves[event.key] + TABS.length) % TABS.length];
    select(next.key);
    buttons.current[next.key]?.focus();
  };

  const { Component } = active;
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div>
            <h1 className={styles.title}>ML Ads</h1>
            <p className={styles.description}>Publicidad de Mercado Libre: aportes de marcas y campañas de Display.</p>
          </div>
          <div ref={setHeaderSlot} className={styles.headerSlot} />
        </div>
        <div className={styles.tabs} role="tablist" aria-label="Secciones de ML Ads" onKeyDown={onKeyDown}>
          {TABS.map((tab) => {
            const selected = tab.key === active.key;
            return (
              <button
                key={tab.key}
                ref={(node) => {
                  buttons.current[tab.key] = node;
                }}
                type="button"
                role="tab"
                id={`ml-ads-tab-${tab.key}`}
                aria-selected={selected}
                aria-controls={PANEL_ID}
                tabIndex={selected ? 0 : -1}
                className={`${styles.tab} ${selected ? styles.active : ''}`}
                onClick={() => select(tab.key)}
              >
                {tab.label}
                {tab.key === 'display' && activeDisplay !== null && (
                  <span className={styles.badge} aria-hidden="true">{`${activeDisplay} Activas`}</span>
                )}
              </button>
            );
          })}
        </div>
      </header>
      <div role="tabpanel" id={PANEL_ID} aria-labelledby={`ml-ads-tab-${active.key}`}>
        <Component headerSlot={headerSlot} onActiveCount={onActiveCount} />
      </div>
    </div>
  );
}
