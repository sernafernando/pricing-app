/**
 * Renovar (tacticals F1): a tactical's detail (`GET /tacticals/{id}`, handoffs/tactical-tarea.md "Contrato final")
 * as the Nuevo tactical screen's values. Same type, header, lines, values and caps; the dates are left empty for the
 * user to pick. Saving it is an ordinary `POST /tacticals`: a NEW tactical, the old one untouched.
 *
 * The detail returns one line per child: the children of a per-product line (`tope_por_producto`) share its `linea`
 * and become one screen line again. An invoice line comes back without its invoice: that invoice already got its
 * bonus, so the user picks the new one.
 */
import { nuevaLinea } from './tacticalLineas';
import { seleccionDesdeDetalle } from './tacticalTiendas';

/** A decimal from the API ("220.00", "3.5") as the screen types it ("220", "3,5"); empty when null. */
const texto = (valor) => (valor == null ? '' : String(Number(valor)).replace('.', ','));

function lineaDe(hijos) {
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
  };
}

export function renovacionDe(tactical, gruposTiendas = []) {
  const porLinea = new Map();
  [...tactical.lineas]
    .sort((a, b) => a.linea - b.linea || a.id - b.id)
    .forEach((hijo) => porLinea.set(hijo.linea, [...(porLinea.get(hijo.linea) ?? []), hijo]));
  return {
    form: {
      tipo: tactical.tipo,
      nombre: tactical.nombre,
      marca: tactical.marca,
      referencia: tactical.referencia ?? '',
      fechaDesde: '',
      fechaHasta: '',
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
    lineas: [...porLinea.values()].map(lineaDe),
  };
}
