/**
 * Productos' stat cards (`Productos.jsx` StatCards, `useProductosFilters` `aplicarFiltroStat`) on Publicaciones ML
 * (S12d4). Each figure is a count of linked products over the screen's filters (`GET /view/stats`), and its click
 * applies the card's filter with these URL keys and values (`usePublicacionesMLFilters`): the card's own filter
 * replaces every other filter a card sets, the rest of the screen's filters (search, brands, ...) stay.
 */

// The filters a card sets, so the ones a click clears (Productos resets exactly these, and `mla`, the Sin MLA card
// of #1845's own key).
export const STAT_FILTER_KEYS = [
  'stock',
  'precio',
  'nuevos',
  'oferta',
  'rebate',
  'webtransf',
  'outofcards',
  'mkclasica',
  'mkrebate',
  'mkoferta',
  'mkwebtransf',
];

/** The URL updates a card's click makes: its `filter`, every other card filter cleared. */
export function statUpdates(filter) {
  return { ...Object.fromEntries(STAT_FILTER_KEYS.map((key) => [key, ''])), ...filter };
}

const sameValue = (current, wanted) => {
  if (Array.isArray(wanted)) return Array.isArray(current) && current.length === wanted.length && wanted.every((v) => current.includes(v));
  return current === wanted;
};
const isOff = (value) => (Array.isArray(value) ? value.length === 0 : !value);

/** True when the screen's card filters are exactly the card's `filter` (its click would change nothing). */
export function isStatActive(filters, filter) {
  return STAT_FILTER_KEYS.every((key) => (key in filter ? sameValue(filters[key], filter[key]) : isOff(filters[key])));
}

/**
 * The cards in Productos' order and wording, each item `{ label, value, filter }` (`reset` for Total, which clears
 * the filters). `value` is null while there is no answer: an unknown figure, never 0.
 */
export function statCardGroups(stats, { canSeeMargin = false } = {}) {
  const value = (key) => stats?.[key] ?? null;
  const groups = [
    { label: 'Total Productos', items: [{ label: 'Total Productos', value: value('total'), reset: true }] },
    {
      label: 'Stock & Precio',
      items: [
        { label: 'Con Stock', value: value('con_stock'), filter: { stock: ['erp_con_stock'] } },
        { label: 'Con Precio', value: value('con_precio'), filter: { precio: 'con_precio' } },
        {
          label: 'Stock sin $',
          value: value('con_stock_sin_precio'),
          filter: { stock: ['erp_con_stock'], precio: 'sin_precio' },
        },
      ],
    },
    {
      label: 'Nuevos (7 días)',
      items: [
        { label: 'Total', value: value('nuevos'), filter: { nuevos: 'ultimos_7_dias' } },
        { label: 'Sin Precio', value: value('nuevos_sin_precio'), filter: { nuevos: 'ultimos_7_dias', precio: 'sin_precio' } },
      ],
    },
    {
      label: 'Oferta sin Rebate',
      items: [
        { label: 'Oferta sin Rebate', value: value('oferta_sin_rebate'), filter: { oferta: 'con_oferta', rebate: 'sin_rebate' } },
      ],
    },
  ];
  if (canSeeMargin) {
    groups.push({
      label: 'Markup Negativo',
      items: [
        { label: 'Clásica', value: value('markup_negativo_clasica'), filter: { mkclasica: 'negativo' } },
        { label: 'Rebate', value: value('markup_negativo_rebate'), filter: { mkrebate: 'negativo' } },
        { label: 'Oferta', value: value('markup_negativo_oferta'), filter: { mkoferta: 'negativo' } },
        { label: 'Web', value: value('markup_negativo_web'), filter: { mkwebtransf: 'negativo' } },
      ],
    });
  }
  return groups;
}
