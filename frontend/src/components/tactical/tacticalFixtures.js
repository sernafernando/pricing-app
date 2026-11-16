/**
 * DERIVED fixtures for the Nuevo tactical screen, taken from the owner-approved OpenDesign screens
 * (handoffs/diseno-tactical/*-aprobado.html), not captured from the API.
 * - CATALOGO: rows of `GET /buscar-productos-catalogo` (ProductoBusqueda: item_id, codigo, descripcion, marca,
 *   categoria) with the design's catalog; the item ids are made up.
 * - OPERACIONES: items of `GET /sell-in/compras/operaciones` (SellInOperacionOut) with the design's invoices; the
 *   operation ids (pedido_compra_id) are made up. `facturas` are the invoices linked to each operation (CT ids made
 *   up): the first has two, the last none yet.
 */
const producto = (item_id, codigo, descripcion, marca, categoria) => ({ item_id, codigo, descripcion, marca, categoria });

export const CATALOGO = [
  producto(101, 'A1B2C3LT', 'AIO HP G2 R5 16G 512 W11H', 'HP', 'All in One'),
  producto(102, 'D4E5F6LT', 'AIO PRO S4 G1 U5225T 24GB 512GB 24"', 'HP', 'All in One'),
  producto(103, '6N1A2LT', 'Notebook HP 250RG10 5-120U', 'HP', 'Notebooks'),
  producto(104, '5C8T3LT', 'Notebook HP 255r G10 R3-7335u 8gb 512gb', 'HP', 'Notebooks'),
  producto(201, 'M24V5LT', 'Monitor HP V24i G5', 'HP', 'Monitores'),
  producto(202, 'M27V5LT', 'Monitor HP V27i G5', 'HP', 'Monitores'),
  producto(203, 'M24P5LT', 'Monitor HP P24 G5', 'HP', 'Monitores'),
  producto(301, 'TPAX55', 'Router TP-Link Archer AX55', 'TP-Link', 'Redes'),
  producto(302, 'TPSG108', 'Switch TP-Link TL-SG108', 'TP-Link', 'Redes'),
];

const factura = (ct_transaction_id, numero, fecha_factura) => ({ ct_transaction_id, numero, fecha_factura });

const operacion = (id, numero, numero_factura, proveedor_id, proveedor_nombre, fecha, monto, facturas = []) => ({
  id,
  numero,
  proveedor_id,
  proveedor_nombre,
  fecha,
  moneda: 'ARS',
  monto,
  estado: 'Recibido',
  numero_factura,
  facturas,
});

export const OPERACIONES = [
  operacion(9001, 'OC 12345', 'FC A 0003-00012345', 40, 'TP-Link Argentina', '2026-10-15', 9480000, [
    factura(70001, 'FC A 0003-00012345', '2026-10-15'),
    factura(70002, 'FC A 0003-00012360', '2026-10-29'),
  ]),
  operacion(9002, 'OC 12346', 'FC A 0003-00012346', 40, 'TP-Link Argentina', '2026-10-22', 5120000, [factura(70010, 'FC A 0003-00012346', '2026-10-22')]),
  operacion(9003, 'OC 12351', 'FC A 0003-00012351', 40, 'TP-Link Argentina', '2026-11-04', 2980000, [factura(70020, null, '2026-11-04')]),
  operacion(9004, 'OC 12398', 'FC A 0003-00012398', 41, 'Nexxt Solutions SA', '2026-10-28', 7640000),
];
