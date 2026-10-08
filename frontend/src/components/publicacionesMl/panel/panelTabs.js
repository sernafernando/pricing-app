import ResumenTab from './ResumenTab';

/**
 * The panel's tab registry. A tab is
 * `{ key, label, isVisible(context), Component }`:
 *  - `isVisible` gets `{ detail, canSeeMargin, canManage }` (see
 *    `PublicationPanel`), so a tab exists only for the data and the permission
 *    that make it worth opening;
 *  - `Component` gets `{ detail, itemId, canSeeMargin, dataState }`.
 *
 * Eventos, Historial, Producto vinculado and Promociones (later PRs) are one
 * entry each here -- the panel itself does not change.
 */
export const PANEL_TABS = [{ key: 'resumen', label: 'Resumen', isVisible: () => true, Component: ResumenTab }];

export function visibleTabs(tabs, context) {
  return tabs.filter((tab) => tab.isVisible(context));
}
