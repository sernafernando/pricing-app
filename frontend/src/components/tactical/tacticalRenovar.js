/**
 * Renovar (tacticals F1): a tactical's detail (`GET /tacticals/{id}`, handoffs/tactical-tarea.md "Contrato final")
 * as the Nuevo tactical screen's values. Same type, header, lines, values and caps; the dates are left empty for the
 * user to pick. Saving it is an ordinary `POST /tacticals`: a NEW tactical, the old one untouched.
 *
 * The detail returns one line per child: the children of a per-product line (`tope_por_producto`) share its `linea`
 * and become one screen line again. An invoice line comes back without its invoice: that invoice already got its
 * bonus, so the user picks the new one.
 *
 * Editar (S8) loads the same values with `edicionDe`: the dates and each invoice line's invoice are kept, since saving
 * replaces this same tactical (`PUT /tacticals/{id}`). `impactoDe` is what the confirmation tells before that save.
 */
import { nuevaLinea } from './tacticalLineas';
import { seleccionDesdeDetalle } from './tacticalTiendas';

/** A decimal from the API ("220.00", "3.5") as the screen types it ("220", "3,5"); empty when null. */
const texto = (valor) => (valor == null ? '' : String(Number(valor)).replace('.', ','));

/** A saved invoice pick as the screen keeps it: nothing when the line covers every invoice of its operation. */
const elegidasDe = (linea) =>
  linea.facturas_ct?.length
    ? { facturasCt: [...linea.facturas_ct], facturasElegidas: linea.facturas_elegidas ?? null }
    : {};

function lineaDe(hijos, conservar) {
  const [primero] = hijos;
  const productos = hijos.flatMap((h) => h.productos ?? []);
  return {
    ...nuevaLinea(),
    alcance: primero.alcance,
    productos: primero.alcance === 'productos' ? productos : [],
    marca: primero.marca ?? '',
    categoria: primero.categoria ?? '',
    // A sell in total of a USD tactical stores its ARS conversion: the renewal loads the USD amount it was typed in.
    monto: texto(primero.valor_usd ?? primero.valor),
    modo: primero.modo_monto,
    topeUnidades: primero.tope_unidades == null ? '' : String(primero.tope_unidades),
    topeMonto: texto(primero.tope_monto),
    // One child with several products is a shared line; several children are one per product.
    compartido: primero.alcance === 'productos' && hijos.length === 1 && productos.length > 1,
    // How a total amount was split among the line's products (sell out or sell in); '' for any other line.
    reparto: primero.reparto_criterio ?? '',
    // Editar keeps the invoice (`id` is the pedido_compra_id) and the invoices it was limited to (varias facturas
    // S3); the picker's details arrive later (`conFacturas`).
    facturas:
      conservar && primero.alcance === 'factura' && primero.pedido_compra_id != null
        ? [{ id: primero.pedido_compra_id, numero: primero.pedido_numero, ...elegidasDe(primero) }]
        : [],
  };
}

function valoresDe(tactical, gruposTiendas, conservar) {
  const porLinea = new Map();
  [...tactical.lineas]
    .sort((a, b) => a.linea - b.linea || a.id - b.id)
    .forEach((hijo) => porLinea.set(hijo.linea, [...(porLinea.get(hijo.linea) ?? []), hijo]));
  return {
    form: {
      tipo: tactical.tipo,
      nombre: tactical.nombre,
      // A tactical read before S3 has only `marca`.
      marcas: tactical.marcas?.length ? [...tactical.marcas] : [tactical.marca].filter(Boolean),
      referencia: tactical.referencia ?? '',
      fechaDesde: conservar ? tactical.fecha_desde ?? '' : '',
      fechaHasta: conservar ? tactical.fecha_hasta ?? '' : '',
      moneda: tactical.moneda,
      tcModo: tactical.tc_modo ?? 'al_cobro',
      tipoCambio: texto(tactical.tipo_cambio),
      incluyeIva: tactical.incluye_iva,
      acumulable: tactical.acumulable,
      todasTiendas: tactical.todas_tiendas !== false,
      topeCompartido: Boolean(tactical.tope_compartido),
      tiendaKeys: seleccionDesdeDetalle(tactical, gruposTiendas),
      nota: tactical.nota ?? '',
    },
    lineas: [...porLinea.values()].map((hijos) => lineaDe(hijos, conservar)),
  };
}

export const renovacionDe = (tactical, gruposTiendas = []) => valoresDe(tactical, gruposTiendas, false);

export const edicionDe = (tactical, gruposTiendas = []) => valoresDe(tactical, gruposTiendas, true);

/** Each invoice line's invoice with the picker's details (`buscadas`: Compras operations), when one was found. */
export const conFacturas = (lineas, buscadas) =>
  lineas.map((l) => ({
    ...l,
    facturas: l.facturas.map((f) => ({ ...f, ...(buscadas.find((b) => b.id === f.id) ?? {}) })),
  }));

/**
 * What saving an edit does to money already applied (S8): `aplicado` per currency and `unidades` over the tactical's
 * active lines (they are recomputed with the new values), and `tcDescartado`, the `al_cobro` rate already set that a
 * change of type, currency or FX mode discards (D2), or null.
 */
export function impactoDe(tactical, form) {
  const activas = tactical.lineas.filter((l) => l.estado === 'activa');
  const aplicado = {};
  activas.forEach((l) => {
    const monto = Number(l.monto_usado ?? 0);
    if (monto) aplicado[l.moneda] = (aplicado[l.moneda] ?? 0) + monto;
  });
  const unidades = activas.reduce((a, l) => a + (l.unidades_usadas ?? 0), 0);
  const tasa = activas.find((l) => l.tc_al_cobro != null)?.tc_al_cobro ?? null;
  const sigue = form.tipo === tactical.tipo && form.moneda === tactical.moneda && form.tcModo === tactical.tc_modo;
  return { aplicado, unidades, tcDescartado: tasa != null && !sigue ? Number(tasa) : null };
}
