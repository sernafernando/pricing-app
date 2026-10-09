import { useId, useRef } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { CopyButton } from '../kit';
import { usePermisos } from '../../contexts/PermisosContext';
import { buildMlItemUrl } from '../../utils/mlSidePanel';
import { describeLoadError } from './loadErrors';
import PublicationStatusPill from './PublicationStatusPill';
import PanelFooter from './panel/PanelFooter';
import { PANEL_TABS, visibleTabs } from './panel/panelTabs';
import { usePublicationDetail } from './panel/usePublicationDetail';
import styles from './panel/panel.module.css';

/** What to tell the operator when the detail cannot be loaded. */
const describeError = (error) =>
  describeLoadError(error, {
    notFound: 'La publicación ya no existe.',
    forbidden: 'No tenés permiso para ver esta publicación.',
    fallback: 'No se pudo cargar la publicación.',
  });

/**
 * The detail of one publication, beside the table (`SplitPanelLayout`).
 *
 * The page owns what is selected and which tab is open (`sel`, `tab` in the
 * URL); the panel loads the detail of `itemId`, decides from it which tabs
 * exist (`tabs` registry) and renders the open one. Escape and focus
 * restoration belong to the layout.
 *
 * @param {object} props
 * @param {string} props.itemId The selected MLA.
 * @param {string} props.tab Key of the open tab (anything unknown is the first one).
 * @param {(key: string) => void} props.onTabChange
 * @param {() => void} props.onClose
 * @param {object} [props.dataState] The list's honest-state block.
 * @param {Array} [props.tabs] The tab registry (tests inject their own).
 */
export default function PublicationPanel({ itemId, tab, onTabChange, onClose, dataState, tabs = PANEL_TABS }) {
  const { tienePermiso } = usePermisos();
  const canSeeMargin = tienePermiso('ml_metricas.ver_ganancia');
  const canManage = tienePermiso('ml_ops.gestionar');
  const { status, detail, error, reload } = usePublicationDetail(itemId, { canSeeMargin });
  const tabRefs = useRef({});
  const panelId = useId();

  const available = detail ? visibleTabs(tabs, { detail, canSeeMargin, canManage }) : [];
  const active = available.find((entry) => entry.key === tab) ?? available[0];

  // Arrow keys / Home / End move between tabs, as a tablist does.
  const handleTabKeyDown = (event) => {
    const index = available.findIndex((entry) => entry.key === active?.key);
    let next = null;
    if (event.key === 'ArrowRight') next = available[(index + 1) % available.length];
    else if (event.key === 'ArrowLeft') next = available[(index - 1 + available.length) % available.length];
    else if (event.key === 'Home') next = available[0];
    else if (event.key === 'End') next = available[available.length - 1];
    if (!next) return;
    event.preventDefault();
    onTabChange(next.key);
    tabRefs.current[next.key]?.focus();
  };

  const row = detail?.row;
  const mlUrl = buildMlItemUrl(row?.permalink);

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <div className={styles.identity}>
          {detail ? <h2 className={styles.title}>{row.title ?? 'Sin título'}</h2> : <h2 className={styles.title}>Publicación</h2>}
          <div className={styles.meta}>
            <span className={styles.itemId}>{itemId}</span>
            <CopyButton value={itemId} label="Copiar MLA" compact />
            {detail && <PublicationStatusPill status={row.status} gone={row.gone} subStatus={detail.subStatus} />}
          </div>
          {mlUrl && (
            <a className={styles.mlLink} href={mlUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={12} aria-hidden="true" />
              Ver en Mercado Libre
            </a>
          )}
        </div>
        <button type="button" className={styles.close} aria-label="Cerrar panel" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      {status === 'loading' && (
        <div className={styles.skeleton} role="status" aria-label="Cargando publicación" aria-busy="true">
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className={styles.skeletonRow} />
          ))}
        </div>
      )}

      {status === 'error' && (
        <div className={styles.error} role="alert">
          <span>{describeError(error)}</span>
          <button type="button" className="btn-tesla outline sm" onClick={reload}>
            Reintentar
          </button>
        </div>
      )}

      {status === 'ready' && active && (
        <>
          <div className={styles.tabs} role="tablist" aria-label="Secciones de la publicación" onKeyDown={handleTabKeyDown}>
            {available.map((entry) => (
              <button
                key={entry.key}
                ref={(node) => {
                  tabRefs.current[entry.key] = node;
                }}
                type="button"
                role="tab"
                id={`${panelId}-tab-${entry.key}`}
                aria-selected={entry.key === active.key}
                aria-controls={`${panelId}-tabpanel`}
                tabIndex={entry.key === active.key ? 0 : -1}
                className={styles.tab}
                onClick={() => onTabChange(entry.key)}
              >
                {entry.label}
              </button>
            ))}
          </div>
          <div className={styles.body} role="tabpanel" id={`${panelId}-tabpanel`} aria-labelledby={`${panelId}-tab-${active.key}`}>
            <active.Component detail={detail} itemId={itemId} canSeeMargin={canSeeMargin} dataState={dataState} />
          </div>
        </>
      )}

      {status === 'ready' && <PanelFooter key={itemId} detail={detail} itemId={itemId} canManage={canManage} />}
    </div>
  );
}
