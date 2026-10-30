/**
 * Bulk void of a sell-in list (`POST /sell-in/{compras,bonos}/anular-masivo`): the backend voids all or nothing,
 * each record through its single void. "Todo lo filtrado" is resolved here, fail-closed: the client pages the list
 * with its filters (stable order, newest first) and refuses to send when the ids do not add up to the total shown.
 */

export const ANULAR_MASIVO_MAX = 500; // `ANULAR_MASIVO_MAX` in backend/app/schemas/sell_in.py
const PAGINA = 200; // the list endpoints' largest page

/**
 * Every voidable id of the filtered list. `listar` is the list API (`sellInAPI.listar` / `sellInBonosAPI.listar`),
 * `params` the filters it is showing with, `total` the count it showed and `generadas` how many of those a brand
 * bonus generated (purchases only): those are voided through their bonus, so they are left out. Throws a message to
 * show when it cannot be trusted: more voidable ones than the bulk limit, an empty answer with filters active, or a
 * count (total or generated) that moved while reading.
 */
export async function resolverIdsFiltrados(listar, params, { total, generadas = 0, filtrosActivos }) {
  const anulables = total - generadas;
  if (anulables > ANULAR_MASIVO_MAX) throw new Error(`Son ${anulables}: se pueden anular hasta ${ANULAR_MASIVO_MAX} por vez. Filtrá más.`);
  const cambio = (n) => new Error(`La lista cambió mientras se seleccionaba (${n} de ${total}). Volvé a intentarlo.`);
  const items = [];
  for (let page = 1; items.length < total; page += 1) {
    const { data } = await listar({ ...params, page, page_size: PAGINA });
    const pagina = data?.items ?? [];
    if (data?.total !== total) throw cambio(data?.total ?? items.length);
    if ((data?.generadas ?? 0) !== generadas) throw cambio(items.length);
    if (pagina.length === 0) break;
    items.push(...pagina);
  }
  const unicos = new Set(items.map((item) => item.id));
  if (unicos.size === 0 && filtrosActivos) throw new Error('No se pudo resolver lo filtrado: la lista vino vacía.');
  if (unicos.size !== total || unicos.size !== items.length) throw cambio(unicos.size);
  const ids = items.filter((item) => item.origen !== 'bono_marca').map((item) => item.id);
  if (ids.length !== anulables) throw cambio(unicos.size);
  return ids;
}

/** The gendered words of a noun ("compra" / "bono"): its article and endings. */
export const generoDe = ({ singular }) => (singular.endsWith('a') ? { o: 'a', los: 'las', alguno: 'alguna', ninguno: 'ninguna' } : { o: 'o', los: 'los', alguno: 'alguno', ninguno: 'ninguno' });

/** "Se anuló 1 compra. 1 ya estaba anulada." from the bulk void's answer. */
export function resultadoDeAnulacion({ anuladas, ya_anuladas: yaAnuladas }, sustantivo) {
  const { o } = generoDe(sustantivo);
  const n = anuladas.length;
  const partes = [n === 1 ? `Se anuló 1 ${sustantivo.singular}.` : `Se anularon ${n} ${sustantivo.plural}.`];
  if (yaAnuladas.length === 1) partes.push(`1 ya estaba anulad${o}.`);
  if (yaAnuladas.length > 1) partes.push(`${yaAnuladas.length} ya estaban anulad${o}s.`);
  return partes.join(' ');
}
