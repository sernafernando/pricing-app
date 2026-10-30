/** Page size used to resolve every filtered campaign: the list endpoint's maximum (`page_size` le=200). */
export const PAGINA_SELECCION = 200;
/** Backend `ANULAR_MASIVO_MAX` (`app/routers/sell_out_campanas.py`). */
export const ANULAR_MASIVO_MAX = 500;

export const SELECCION_CAMBIADA = 'La lista de campañas cambió mientras se seleccionaba. Actualizá la lista y volvé a intentar.';

/**
 * Every campaign the list's filters match, as `Map(id → estado)`, paging `GET /sell-out/campanas` in its stable
 * order (start date desc, id desc). Fail-closed: throws `SELECCION_CAMBIADA` when a page reports another total, when
 * the ids do not add up to `total` (what the list shows), or when nothing comes back while filters are active.
 */
export async function resolverFiltradas(listar, filtros, total) {
  const filtrado = Object.values(filtros).some((v) => v != null && String(v).trim() !== '');
  const ids = new Map();
  for (let page = 1; ; page += 1) {
    const { data } = await listar({ ...filtros, page, page_size: PAGINA_SELECCION });
    if (data.total !== total) throw new Error(SELECCION_CAMBIADA);
    data.items.forEach((c) => ids.set(c.id, c.estado));
    if (data.items.length < PAGINA_SELECCION || page * PAGINA_SELECCION >= data.total) break;
  }
  if (ids.size !== total || (ids.size === 0 && filtrado)) throw new Error(SELECCION_CAMBIADA);
  return ids;
}

const plural = (n, uno, varios) => (n === 1 ? uno : varios);

/** "Se van a anular 2 campañas." plus the already voided ones the backend skips. */
export function textoConfirmacion(activas, yaAnuladas) {
  const partes = [plural(activas, 'Se va a anular 1 campaña.', `Se van a anular ${activas} campañas.`)];
  if (yaAnuladas > 0) {
    partes.push(plural(yaAnuladas, '1 ya está anulada y se omite.', `${yaAnuladas} ya están anuladas y se omiten.`));
  }
  return partes.join(' ');
}

/** The result of `POST /sell-out/campanas/anular`: voided and skipped. */
export function textoResultado({ anuladas, omitidas }) {
  const partes = [
    anuladas.length === 0
      ? 'No había campañas activas para anular.'
      : plural(anuladas.length, 'Se anuló 1 campaña.', `Se anularon ${anuladas.length} campañas.`),
  ];
  if (omitidas.length > 0) {
    partes.push(
      plural(omitidas.length, '1 ya estaba anulada y se omitió.', `${omitidas.length} ya estaban anuladas y se omitieron.`),
    );
  }
  return partes.join(' ');
}
