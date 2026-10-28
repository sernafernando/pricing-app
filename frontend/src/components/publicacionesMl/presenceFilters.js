import { BarChart3, CreditCard, Gift, ShoppingCart, Sparkles } from 'lucide-react';

/**
 * Productos' "Filtros de Presencia" on Publicaciones ML, plus its Precio and Productos Nuevos selects: the same
 * toggles, URL keys, values and labels as the Productos advanced filters panel. The URL keys and what each value asks the backend live in
 * `usePublicacionesMLFilters` (`PRESENCE_VALUES`); this module is their labels. Productos' emoji are not carried
 * over: the toggles that have an icon there get a lucide one, and the option labels are plain text.
 */
export const PRESENCE_FILTERS = [
  { key: 'rebate', icon: Gift, name: 'Rebate', options: [['con_rebate', 'Con Rebate'], ['sin_rebate', 'Sin Rebate']] },
  { key: 'oferta', name: 'Mejor Oferta', options: [['con_oferta', 'Con Oferta'], ['sin_oferta', 'Sin Oferta']] },
  {
    key: 'webtransf',
    icon: CreditCard,
    name: 'Web Transferencia',
    options: [['con_web_transf', 'Con Web Transf.'], ['sin_web_transf', 'Sin Web Transf.']],
  },
  {
    key: 'tiendanube',
    icon: ShoppingCart,
    name: 'Tienda Nube',
    options: [['con_descuento', 'Con Descuento'], ['sin_descuento', 'Sin Descuento'], ['no_publicado', 'No Publicado']],
  },
  {
    key: 'outofcards',
    name: 'Out of Cards',
    options: [['con_out_of_cards', 'Marcados'], ['sin_out_of_cards', 'No Marcados']],
  },
  // Productos' "Precio" select and its advanced "Productos Nuevos" one: both ask the linked product.
  { key: 'precio', name: 'Precio', options: [['con_precio', 'Con precio'], ['sin_precio', 'Sin precio']] },
  { key: 'nuevos', icon: Sparkles, name: 'Productos Nuevos', options: [['ultimos_7_dias', 'Últimos 7 días']] },
  // Productos' "Estado MLA" select, product level: Pausadas are the products with publications and none active.
  { key: 'estado_mla', icon: BarChart3, name: 'Estado MLA', options: [['pausada', 'Pausadas']] },
];

/** Productos' four markup selects: only for a user with `ml_metricas.ver_ganancia` (`usePublicacionesMLFilters`). */
const SIGNS = [['positivo', 'Positivo'], ['negativo', 'Negativo']];
export const MARKUP_SIGN_FILTERS = [
  { key: 'mkclasica', name: 'Markup Clásica', options: SIGNS },
  { key: 'mkrebate', name: 'Markup Rebate', options: SIGNS },
  { key: 'mkoferta', name: 'Markup Oferta', options: SIGNS },
  { key: 'mkwebtransf', name: 'Markup Web Transf.', options: SIGNS },
];

export const EMPTY_PRESENCE_FILTERS = Object.fromEntries(
  [...PRESENCE_FILTERS, ...MARKUP_SIGN_FILTERS].map(({ key }) => [key, '']),
);

/** One chip per active toggle: "<toggle>: <value>", and the `setFilters` update that clears it. */
export function activePresenceChips(filters) {
  return [...PRESENCE_FILTERS, ...MARKUP_SIGN_FILTERS].flatMap(({ key, name, options }) => {
    const option = options.find(([value]) => value === filters[key]);
    return option ? [{ id: key, label: `${name}: ${option[1]}`, remove: { [key]: '' } }] : [];
  });
}
