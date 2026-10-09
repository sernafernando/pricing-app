import EventosTab from './EventosTab';
import FullTab from './FullTab';
import HistorialTab from './HistorialTab';
import ProductoVinculadoTab from './ProductoVinculadoTab';
import PromocionesTab from './PromocionesTab';
import ResumenTab from './ResumenTab';
import VariacionesTab from './VariacionesTab';

/**
 * The panel's tab registry. A tab is
 * `{ key, label, isVisible(context), Component }`:
 *  - `isVisible` gets `{ detail, canSeeMargin, canManage, canViewPromos }` (see
 *    `PublicationPanel`), so a tab exists only for the data and the permission
 *    that make it worth opening;
 *  - `Component` gets `{ detail, itemId, canSeeMargin, dataState, onPromoApplied }`.
 *
 * Eventos and Historial load their own pages when opened (they cost a request
 * only when somebody looks at them); Producto vinculado reads the detail.
 */
export const PANEL_TABS = [
  { key: 'resumen', label: 'Resumen', isVisible: () => true, Component: ResumenTab },
  { key: 'variaciones', label: 'Variaciones', isVisible: ({ detail }) => detail.variationsCount > 0, Component: VariacionesTab },
  { key: 'full', label: 'Full', isVisible: ({ detail }) => detail.isFull || detail.replenishment != null, Component: FullTab },
  { key: 'promociones', label: 'Promos', isVisible: ({ canViewPromos }) => Boolean(canViewPromos), Component: PromocionesTab },
  { key: 'eventos', label: 'Eventos', isVisible: () => true, Component: EventosTab },
  { key: 'historial', label: 'Historial', isVisible: () => true, Component: HistorialTab },
  { key: 'producto', label: 'Producto', isVisible: () => true, Component: ProductoVinculadoTab },
];

export function visibleTabs(tabs, context) {
  return tabs.filter((tab) => tab.isVisible(context));
}
