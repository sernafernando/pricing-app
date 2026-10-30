/**
 * Bulk void of a sell-in list (`POST /sell-in/{compras,bonos}/anular-masivo`): the backend voids all or nothing,
 * each record through its single void. "Todo lo filtrado" is resolved here, fail-closed: the client pages the list
 * with its filters (stable order, newest first) and refuses to send when the ids do not add up to the total shown.
 */

export const ANULAR_MASIVO_MAX = 500; // `ANULAR_MASIVO_MAX` in backend/app/schemas/sell_in.py
const PAGINA = 200; // the list endpoints' largest page

/**
 * Every id of the filtered list. `listar` is the list API (`sellInAPI.listar` / `sellInBonosAPI.listar`), `params`
 * the filters it is showing with, `total` the count it showed. Throws a message to show when it cannot be trusted:
 * more than the bulk limit, an empty answer with filters active, or a count that moved while reading.
 */
export async function resolverIdsFiltrados(listar, params, { total, filtrosActivos }) {
  if (total > ANULAR_MASIVO_MAX) throw new Error(`Son ${total}: se pueden anular hasta ${ANULAR_MASIVO_MAX} por vez. Filtrá más.`);
  const cambio = (n) => new Error(`La lista cambió mientras se seleccionaba (${n} de ${total}). Volvé a intentarlo.`);
  const ids = [];
  for (let page = 1; ids.length < total; page += 1) {
    const { data } = await listar({ ...params, page, page_size: PAGINA });
    const items = data?.items ?? [];
    if (data?.total !== total) throw cambio(data?.total ?? ids.length);
    if (items.length === 0) break;
    ids.push(...items.map((item) => item.id));
  }
  const unicos = [...new Set(ids)];
  if (unicos.length === 0 && filtrosActivos) throw new Error('No se pudo resolver lo filtrado: la lista vino vacía.');
  if (unicos.length !== total || unicos.length !== ids.length) throw cambio(unicos.length);
  return unicos;
}

/** "Se anuló 1 compra. 1 ya estaba anulada." from the bulk void's answer. */
export function resultadoDeAnulacion({ anuladas, ya_anuladas: yaAnuladas }, { singular, plural }) {
  const n = anuladas.length;
  const partes = [n === 1 ? `Se anuló 1 ${singular}.` : `Se anularon ${n} ${plural}.`];
  if (yaAnuladas.length === 1) partes.push(`1 ya estaba anulad${singular.endsWith('a') ? 'a' : 'o'}.`);
  if (yaAnuladas.length > 1) partes.push(`${yaAnuladas.length} ya estaban anulad${singular.endsWith('a') ? 'as' : 'os'}.`);
  return partes.join(' ');
}
