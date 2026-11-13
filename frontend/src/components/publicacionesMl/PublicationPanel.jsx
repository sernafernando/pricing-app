import { useEffect, useState } from 'react';
import { ArrowLeft, ExternalLink, Sparkles } from 'lucide-react';
import { CopyButton } from '../kit';
import { usePermisos } from '../../contexts/PermisosContext';
import { buildMlItemUrl } from '../../utils/mlSidePanel';
import { describeLoadError } from './loadErrors';
import ListingKindBadge from './ListingKindBadge';
import MlSellerLinks from './MlSellerLinks';
import PublicationStatusPill from './PublicationStatusPill';
import PanelFooter from './panel/PanelFooter';
import PanelShell from './panel/PanelShell';
import PanelTabs from './panel/PanelTabs';
import { PANEL_TABS, visibleTabs } from './panel/panelTabs';
import { canViewProductPrices } from '../pricing/productPricePermissions';
import { usePublicationDetail } from './panel/usePublicationDetail';
import PanelFigures from './panel/PanelFigures';
import MejoresCandidatasBlock from './panel/MejoresCandidatasBlock';
import PonerPreciosBody from './panel/PonerPreciosBody';
import { publicationFigures } from './panel/publicationFigures';
import { pricePermissions } from '../pricing/productPricePermissions';
import useIsPhone from '../../hooks/useIsPhone';
import PhonePanelActions from './mobile/PhonePanelActions';
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
 * @param {object} [props.priceGroup] What the Precios tab takes from the list (Calcular, the Tienda Nube price).
 * @param {boolean} [props.ponerPreciosMode] MODO PONER PRECIOS: no tabs, minimal price body (S5).
 * @param {boolean} [props.competenciaOpen] Promos Ver competencia: whether the ranking column is open.
 * @param {(open: boolean) => void} [props.onCompetenciaOpenChange]
 * @param {(shown: boolean) => void} [props.onCompetenciaShownChange] Whether the ranking is on screen (widens the split).
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
  priceGroup = null,
  ponerPreciosMode = false,
  competenciaOpen = false,
  onCompetenciaOpenChange,
  onCompetenciaShownChange,
}) {
  const { tienePermiso } = usePermisos();
  const canSeeMargin = tienePermiso('ml_metricas.ver_ganancia');
  const canSeeSales = tienePermiso('ml_metricas.ver');
  const canManage = tienePermiso('ml_ops.gestionar');
  const canViewPromos = tienePermiso('promos.ver');
  const canViewPrices = canViewProductPrices(tienePermiso);
  const canEditPrice = ['canEditClasica', 'canEditMlCuotas'].some((flag) => pricePermissions(tienePermiso)[flag]);
  const canWritePromos = tienePermiso('promos.escribir');
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
  // On a phone the ML link and the seller panel's links are the top bar's icons, not the MLA line's (PubDetalle design).
  const phone = useIsPhone();
  // Outside MODO: chooser is a block above tabs (never replaces them). Hide after
  // discard; when its candidates are unavailable it stays as a notice that can still
  // discard the flag. Reset when switching publication.
  const [mejoresBlockOpen, setMejoresBlockOpen] = useState(true);
  // The block's suggested promotion ids, marked "Sugerida" in the Promos tab.
  const [suggestedIds, setSuggestedIds] = useState([]);
  // Once shown for this publication, the block stays until Descartar: a silent refresh after a write
  // may clear the flag, and unmounting would drop what the block still says (the "price differs" alert).
  const [mejoresShown, setMejoresShown] = useState(false);
  useEffect(() => {
    setMejoresBlockOpen(true);
    setSuggestedIds([]);
    setMejoresShown(false);
  }, [itemId]);
  const hayMejores = Boolean(detail?.row?.hay_mejores_ofertas);
  useEffect(() => {
    if (hayMejores) setMejoresShown(true);
  }, [hayMejores]);
  const showMejoresBlock =
    !ponerPreciosMode &&
    canWritePromos &&
    (hayMejores || mejoresShown) &&
    mejoresBlockOpen;
  // Without promos.escribir the flag is still news: a read-only notice, as the old Promos-tab banner.
  const showMejoresReadOnly = !ponerPreciosMode && !canWritePromos && canViewPromos && hayMejores;
  const closeMejoresBlock = () => {
    setMejoresBlockOpen(false);
    setSuggestedIds([]);
  };

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
            {detail && <ListingKindBadge kind={row.listing_kind} />}
            {!phone && <MlSellerLinks itemId={itemId} />}
            {detail && <PublicationStatusPill status={row.status} gone={row.gone} subStatus={detail.subStatus} />}
            {/* On the MLA line, after its badges, as the approved design. */}
            {mlUrl && !phone && (
              <a className={styles.mlLink} href={mlUrl} target="_blank" rel="noopener noreferrer">
                Ver en Mercado Libre
                <ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
          </div>
        </>
      }
      figures={
        !ponerPreciosMode &&
        detail && <PanelFigures label="Cifras de la publicación" figures={publicationFigures(row, { canSeeMargin, canSeeSales, breakdown: detail.markupBreakdown, sellInOut: detail.sellInOut })} />
      }
      onClose={onClose}
      phoneActions={phone ? <PhonePanelActions itemId={itemId} mlUrl={mlUrl} /> : null}
      loading={status === 'loading'}
      loadingLabel="Cargando publicación"
      error={status === 'error' ? describeError(error) : null}
      onRetry={reload}
    >
      {status === 'ready' && ponerPreciosMode && (
        <PonerPreciosBody
          key={itemId}
          detail={detail}
          itemId={itemId}
          canEditPrice={canEditPrice}
          canWritePromos={canWritePromos}
          onWritten={handleWritten}
          onLeavePub={onClose}
        />
      )}

      {status === 'ready' && showMejoresReadOnly && (
        <p className={styles.mejoresReadOnly} role="status" aria-label="Candidatas mejores">
          <Sparkles size={14} aria-hidden="true" className={styles.mejoresIcon} />
          Hay candidatas mejores que el precio vigente en MeLi.
        </p>
      )}

      {status === 'ready' && showMejoresBlock && (
        <MejoresCandidatasBlock
          key={`mejores-${itemId}`}
          itemId={itemId}
          baselinePrice={row?.price?.amount}
          onWritten={handleWritten}
          onDismissed={closeMejoresBlock}
          onSuggested={setSuggestedIds}
        />
      )}

      {status === 'ready' && !ponerPreciosMode && active && (
        <PanelTabs tabs={available} activeKey={active.key} onTabChange={onTabChange} label="Secciones de la publicación">
          <active.Component
            detail={detail}
            itemId={itemId}
            canSeeMargin={canSeeMargin}
            canViewPromos={canViewPromos}
            dataState={dataState}
            onPromoApplied={handleWritten}
            onWritten={handleWritten}
            priceGroup={priceGroup}
            suggestedPromotionIds={showMejoresBlock ? suggestedIds : undefined}
            competenciaOpen={competenciaOpen}
            onCompetenciaOpenChange={onCompetenciaOpenChange}
            onCompetenciaShownChange={onCompetenciaShownChange}
          />
        </PanelTabs>
      )}

      {status === 'ready' && !ponerPreciosMode && (
        <PanelFooter key={itemId} detail={detail} itemId={itemId} canManage={canManage} onStatusChanged={handleWritten} />
      )}
    </PanelShell>
  );
}
