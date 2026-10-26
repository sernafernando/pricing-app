import { ArrowLeft, ExternalLink } from 'lucide-react';
import { CopyButton } from '../kit';
import { usePermisos } from '../../contexts/PermisosContext';
import { buildMlItemUrl } from '../../utils/mlSidePanel';
import { describeLoadError } from './loadErrors';
import MlSellerLinks from './MlSellerLinks';
import PublicationStatusPill from './PublicationStatusPill';
import PanelFooter from './panel/PanelFooter';
import PanelShell from './panel/PanelShell';
import PanelTabs from './panel/PanelTabs';
import { PANEL_TABS, visibleTabs } from './panel/panelTabs';
import { canViewProductPrices } from '../pricing/productPricePermissions';
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
 * @param {() => void} [props.onListReload] Asks the page to reload its list (a promotion write changes price and markup).
 * @param {object} [props.dataState] The list's honest-state block.
 * @param {Array} [props.tabs] The tab registry (tests inject their own).
 * @param {() => void} [props.onBack] Shows "Volver a <producto>": the publication was opened from a product's panel.
 * @param {string} [props.backLabel] The product's name for that link ("Volver al producto" without it).
 */
export default function PublicationPanel({
  itemId,
  tab,
  onTabChange,
  onClose,
  onListReload,
  dataState,
  tabs = PANEL_TABS,
  onBack,
  backLabel,
}) {
  const { tienePermiso } = usePermisos();
  const canSeeMargin = tienePermiso('ml_metricas.ver_ganancia');
  const canManage = tienePermiso('ml_ops.gestionar');
  const canViewPromos = tienePermiso('promos.ver');
  const canViewPrices = canViewProductPrices(tienePermiso);
  const { status, detail, error, reload, refresh } = usePublicationDetail(itemId, { canSeeMargin });
  // A write in a tab (a promotion, a product price) changes what the detail and the
  // list row show: re-read both, the detail silently so the tab keeps its state.
  const handleWritten = () => {
    refresh();
    onListReload?.();
  };

  const available = detail ? visibleTabs(tabs, { detail, canSeeMargin, canManage, canViewPromos, canViewPrices }) : [];
  const active = available.find((entry) => entry.key === tab) ?? available[0];

  const row = detail?.row;
  const mlUrl = buildMlItemUrl(row?.permalink);

  return (
    <PanelShell
      title={detail ? (row.title ?? 'Sin título') : 'Publicación'}
      meta={
        <>
          {onBack && (
            <button type="button" className={styles.back} onClick={onBack}>
              <ArrowLeft size={12} aria-hidden="true" />
              <span className={styles.backText}>{backLabel ? `Volver a ${backLabel}` : 'Volver al producto'}</span>
            </button>
          )}
          <div className={styles.meta}>
            <span className={styles.itemId}>{itemId}</span>
            <CopyButton value={itemId} label="Copiar MLA" compact />
            <MlSellerLinks itemId={itemId} />
            {detail && <PublicationStatusPill status={row.status} gone={row.gone} subStatus={detail.subStatus} />}
          </div>
          {mlUrl && (
            <a className={styles.mlLink} href={mlUrl} target="_blank" rel="noopener noreferrer">
              <ExternalLink size={12} aria-hidden="true" />
              Ver en Mercado Libre
            </a>
          )}
        </>
      }
      onClose={onClose}
      loading={status === 'loading'}
      loadingLabel="Cargando publicación"
      error={status === 'error' ? describeError(error) : null}
      onRetry={reload}
    >
      {status === 'ready' && active && (
        <PanelTabs tabs={available} activeKey={active.key} onTabChange={onTabChange} label="Secciones de la publicación">
          <active.Component detail={detail} itemId={itemId} canSeeMargin={canSeeMargin} dataState={dataState} onPromoApplied={handleWritten} onWritten={handleWritten} />
        </PanelTabs>
      )}

      {status === 'ready' && <PanelFooter key={itemId} detail={detail} itemId={itemId} canManage={canManage} onStatusChanged={handleWritten} />}
    </PanelShell>
  );
}
