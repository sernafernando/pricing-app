import DatosTab from './DatosTab';
import EventosTab from './EventosTab';
import FullTab from './FullTab';
import HistorialTab from './HistorialTab';
import PreciosTab from './PreciosTab';
import ProductoVinculadoTab from './ProductoVinculadoTab';
import PromocionesTab from './PromocionesTab';
import ResumenTab from './ResumenTab';
import VariacionesTab from './VariacionesTab';

/**
 * The panel's tab registry. A tab is
 * `{ key, label, isVisible(context), Component }`:
 *  - `isVisible` gets `{ detail, canSeeMargin, canManage, canViewPromos, canViewPrices }` (see
 *    `PublicationPanel`), so a tab exists only for the data and the permission
 *    that make it worth opening;
 *  - `Component` gets `{ detail, itemId, canSeeMargin, dataState, onPromoApplied, onWritten, priceGroup }`.
 *
 * Eventos and Historial load their own pages when opened (they cost a request
 * only when somebody looks at them), and so does Datos; Producto vinculado reads the detail.
 *
 * The order is the panel's: it opens on the first tab that exists (owner, 2026-11-02: promos or prices first),
 * so Promos, then Precios, then Resumen. A new tab goes here, where it should sit.
 */
export const PANEL_TABS = [
  { key: 'promociones', label: 'Promos', isVisible: ({ canViewPromos }) => Boolean(canViewPromos), Component: PromocionesTab },
  {
    key: 'precios',
    label: 'Precios',
    isVisible: ({ detail, canViewPrices }) => Boolean(canViewPrices) && detail.product != null,
    Component: PreciosTab,
  },
  { key: 'resumen', label: 'Resumen', isVisible: () => true, Component: ResumenTab },
  { key: 'datos', label: 'Datos', isVisible: () => true, Component: DatosTab },
  { key: 'variaciones', label: 'Variaciones', isVisible: ({ detail }) => detail.variationsCount > 0, Component: VariacionesTab },
  { key: 'full', label: 'Full', isVisible: ({ detail }) => detail.isFull || detail.replenishment != null, Component: FullTab },
  { key: 'eventos', label: 'Eventos', isVisible: () => true, Component: EventosTab },
  { key: 'historial', label: 'Historial', isVisible: () => true, Component: HistorialTab },
  { key: 'producto', label: 'Producto', isVisible: () => true, Component: ProductoVinculadoTab },
];

export function visibleTabs(tabs, context) {
  return tabs.filter((tab) => tab.isVisible(context));
}
