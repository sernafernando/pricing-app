/**
 * Productos' "Filtros de Presencia" on Publicaciones ML: the same five toggles, URL keys, values and labels as the
 * Productos advanced filters panel. The URL keys and what each value asks the backend live in
 * `usePublicacionesMLFilters` (`PRESENCE_VALUES`); this module is their labels.
 */
export const PRESENCE_FILTERS = [
  { key: 'rebate', icon: '🎁', name: 'Rebate', options: [['con_rebate', 'Con Rebate'], ['sin_rebate', 'Sin Rebate']] },
  { key: 'oferta', name: 'Mejor Oferta', options: [['con_oferta', 'Con Oferta'], ['sin_oferta', 'Sin Oferta']] },
  {
    key: 'webtransf',
    icon: '💳',
    name: 'Web Transferencia',
    options: [['con_web_transf', 'Con Web Transf.'], ['sin_web_transf', 'Sin Web Transf.']],
  },
  {
    key: 'tiendanube',
    icon: '🛒',
    name: 'Tienda Nube',
    options: [['con_descuento', 'Con Descuento'], ['sin_descuento', '💵 Sin Descuento'], ['no_publicado', '📦 No Publicado']],
  },
  {
    key: 'outofcards',
    name: 'Out of Cards',
    options: [['con_out_of_cards', 'Marcados'], ['sin_out_of_cards', 'No Marcados']],
  },
];

export const EMPTY_PRESENCE_FILTERS = Object.fromEntries(PRESENCE_FILTERS.map(({ key }) => [key, '']));

/** One chip per active toggle: "<toggle>: <value>", and the `setFilters` update that clears it. */
export function activePresenceChips(filters) {
  return PRESENCE_FILTERS.flatMap(({ key, name, options }) => {
    const option = options.find(([value]) => value === filters[key]);
    return option ? [{ id: key, label: `${name}: ${option[1]}`, remove: { [key]: '' } }] : [];
  });
}
