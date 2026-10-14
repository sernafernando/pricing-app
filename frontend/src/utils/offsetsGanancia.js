/**
 * Profit offsets applied to a product's cost: the "markup con offsets aplicados"
 * Productos shows beside the clásica markup ("→ X%"), as pure functions so
 * every screen that shows it (Productos, the Publicaciones ML Precios tab)
 * computes the same figure from the same offsets.
 *
 * Only offsets WITHOUT limits and of type `porcentaje_costo` or
 * `monto_por_unidad` count (never `monto_fijo`): a capped or fixed offset has
 * no per-unit meaning for a price.
 */

const DEFAULT_TIPO_CAMBIO = 1000;

/** The flag of `OffsetGananciaResponse` that says an offset reaches each sales channel. */
const CANAL_FLAG = { ml: 'aplica_ml', fuera: 'aplica_fuera', tienda_nube: 'aplica_tienda_nube' };

/** The offsets that discount the unit cost: uncapped percentage or per-unit amount. */
export function offsetsSinLimite(offsets) {
  return (offsets || []).filter(
    (o) =>
      !o.max_unidades &&
      !o.max_monto_usd &&
      (o.tipo_offset === 'porcentaje_costo' || o.tipo_offset === 'monto_por_unidad'),
  );
}

/**
 * Reads the current offsets, today's USD rate and the filters of every group
 * those offsets use. `fetchers` are the calls to make (each resolves to an
 * axios-like `{ data }`): `offsets()`, `tipoCambio()` and `grupoFiltros(id)`.
 *
 * With a `tipoCambio` fetcher a missing rate falls back to 1000 (Productos'
 * behaviour). Without one no rate is read and `tipoCambio` is null: the caller
 * brings its own and never gets an assumed one.
 */
export async function cargarOffsetsVigentes(fetchers) {
  const [offsetsRes, tcRes] = await Promise.all([fetchers.offsets(), fetchers.tipoCambio ? fetchers.tipoCambio() : null]);
  const tipoCambio = fetchers.tipoCambio ? tcRes?.data?.tipo_cambio || DEFAULT_TIPO_CAMBIO : null;
  const offsets = offsetsSinLimite(offsetsRes?.data);

  const grupoIds = [...new Set(offsets.filter((o) => o.grupo_id).map((o) => o.grupo_id))];
  const grupoFiltros = {};
  if (grupoIds.length > 0) {
    try {
      const filtrosRes = await Promise.all(grupoIds.map((id) => fetchers.grupoFiltros(id)));
      grupoIds.forEach((id, idx) => {
        grupoFiltros[id] = filtrosRes[idx]?.data || [];
      });
    } catch {
      // Without its filters a group offset matches nothing; the other offsets still apply.
    }
  }
  return { offsets, grupoFiltros, tipoCambio };
}

/** Whether an offset reaches the product: a group by any of its filters, else by item/subcategory/category/brand. */
function aplica(offset, producto, grupoFiltros) {
  if (offset.grupo_id) {
    const filtros = grupoFiltros[offset.grupo_id] || [];
    return filtros.some(
      (f) =>
        (!f.marca || f.marca === producto.marca) &&
        (!f.categoria || f.categoria === producto.categoria) &&
        (!f.subcategoria_id || f.subcategoria_id === producto.subcategoria_id) &&
        (!f.item_id || f.item_id === producto.item_id),
    );
  }
  return Boolean(
    (offset.item_id && offset.item_id === producto.item_id) ||
      (offset.subcategoria_id && offset.subcategoria_id === producto.subcategoria_id) ||
      (offset.categoria && offset.categoria === producto.categoria) ||
      (offset.marca && offset.marca === producto.marca),
  );
}

/** The offsets that reach the product on the channel (all of them without one). */
function offsetsQueAplican(producto, { offsets, grupoFiltros, canal }) {
  const flag = canal ? CANAL_FLAG[canal] : null;
  return (offsets || []).filter((offset) => !(flag && offset[flag] === false) && aplica(offset, producto, grupoFiltros || {}));
}

/**
 * Whether the cost with offset needs a USD rate: a USD cost, or a USD
 * per-unit offset that reaches the product (on `canal`, when given).
 */
export function requiereTipoCambio(producto, contexto) {
  if (producto?.moneda_costo === 'USD') return true;
  return offsetsQueAplican(producto, contexto).some((o) => o.tipo_offset === 'monto_por_unidad' && o.moneda === 'USD');
}

/**
 * The product's cost in ARS with the offsets that reach it discounted:
 * `{ costoARS, descuento, costoAjustado, aplicados: [{ id, descripcion, monto }] }`
 * (`monto` is each offset's discount in ARS), or null when there is no
 * positive cost, nothing applies, it adds up to 0 or it leaves no cost.
 *
 * With `canal` (`ml`, `fuera`, `tienda_nube`) an offset whose `aplica_<canal>`
 * is false is skipped (a missing flag applies, the backend default); without
 * it every offset counts, as Productos does.
 *
 * @param {object} producto `costo`, `moneda_costo` and the fields offsets match on.
 * @param {{ offsets: object[], grupoFiltros: object, tipoCambio: number|null, canal?: string }} contexto
 */
export function costoConOffset(producto, { offsets, grupoFiltros, tipoCambio, canal }) {
  if (!producto?.costo || producto.costo <= 0) return null;
  if (!offsets || offsets.length === 0) return null;

  const costoARS = producto.moneda_costo === 'USD' && tipoCambio ? producto.costo * tipoCambio : producto.costo;

  const aplicados = [];
  let descuento = 0;
  for (const offset of offsetsQueAplican(producto, { offsets, grupoFiltros, canal })) {
    let monto = 0;
    if (offset.tipo_offset === 'porcentaje_costo') {
      monto = costoARS * ((offset.porcentaje || 0) / 100);
    } else if (offset.tipo_offset === 'monto_por_unidad') {
      monto = offset.moneda === 'USD' && tipoCambio ? (offset.monto || 0) * tipoCambio : offset.monto || 0;
    }
    descuento += monto;
    aplicados.push({ id: offset.id, descripcion: offset.descripcion ?? null, monto });
  }

  if (aplicados.length === 0 || descuento === 0) return null;
  const costoAjustado = costoARS - descuento;
  if (costoAjustado <= 0) return null;
  return { costoARS, descuento, costoAjustado, aplicados };
}

/**
 * A markup (percent) recomputed over the offset cost: the same net price
 * (`(1 + markup) * costo`) over `costoAjustado`, rounded to 2 decimals. Null
 * without a markup (0 is a real one) or without an offset cost.
 */
export function markupConOffset(markup, costo) {
  if (markup === null || markup === undefined || markup === '' || !costo) return null;
  const limpio = (Number(markup) / 100 + 1) * costo.costoARS;
  const markupNuevo = (limpio / costo.costoAjustado - 1) * 100;
  return Math.round(markupNuevo * 100) / 100;
}
