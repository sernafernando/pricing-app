/**
 * TrazaClienteViewer -- Componente de traza por cliente.
 *
 * Muestra la info del cliente + lista de transacciones expandibles.
 * Cada transaccion se expande para mostrar lineas de producto con seriales.
 *
 * Estructura:
 *   ClienteHeader  -> datos del cliente (nombre, CUIT, ML, etc.)
 *   Transacciones  -> tabla expandible (fecha, documento, total)
 *     -> Lineas    -> productos + seriales
 *
 * Props:
 *   data       -- TrazaClienteResponse del backend
 *   onPageChange -- callback(page) para paginacion
 *   page       -- pagina actual
 *   pageSize   -- tamano de pagina
 *   compact    -- boolean, reduce padding (para modales)
 */

import { useState, Fragment } from 'react';
import {
  ChevronRight,
  User,
  Mail,
  Phone,
  MapPin,
  FileText,
  Package,
  ShoppingCart,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  AlertCircle,
  AlertTriangle,
  Wrench,
  ScanBarcode,
  Calendar,
} from 'lucide-react';
import styles from './TrazaClienteViewer.module.css';

function formatFecha(fecha) {
  if (!fecha) return '\u2014';
  try {
    const d = new Date(fecha);
    return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return fecha;
  }
}

function formatPrecio(valor) {
  if (valor == null) return null;
  return `$${Number(valor).toLocaleString('es-AR', { minimumFractionDigits: 2 })}`;
}

// -- Cliente header ---------------------------------------------------------
function ClienteHeader({ cliente }) {
  if (!cliente) return null;

  return (
    <div className={styles.clienteCard}>
      <div className={styles.clienteMain}>
        <div className={styles.clienteNombre}>
          <User size={16} />
          <strong>{cliente.nombre}</strong>
          {cliente.nombre_alt && (
            <span className={styles.nombreAlt}>{cliente.nombre_alt}</span>
          )}
          <span className={styles.custIdBadge}>#{cliente.cust_id}</span>
          {cliente.inactivo && (
            <span className={styles.inactivoBadge}>
              <AlertCircle size={11} /> Inactivo
            </span>
          )}
        </div>
      </div>

      <div className={styles.clienteMeta}>
        {cliente.cuit_dni && (
          <span className={styles.metaItem}>
            <FileText size={12} />
            {cliente.tipo_documento && `${cliente.tipo_documento}: `}
            {cliente.cuit_dni}
          </span>
        )}
        {cliente.clase_fiscal && (
          <span className={styles.metaItem}>{cliente.clase_fiscal}</span>
        )}
        {cliente.email && (
          <span className={styles.metaItem}>
            <Mail size={12} /> {cliente.email}
          </span>
        )}
        {(cliente.telefono || cliente.celular) && (
          <span className={styles.metaItem}>
            <Phone size={12} /> {cliente.celular || cliente.telefono}
          </span>
        )}
        {(cliente.direccion || cliente.ciudad) && (
          <span className={styles.metaItem}>
            <MapPin size={12} />
            {[cliente.direccion, cliente.ciudad].filter(Boolean).join(', ')}
          </span>
        )}
        {cliente.ml_nickname && (
          <span className={styles.mlBadge}>
            <ShoppingCart size={12} /> {cliente.ml_nickname}
          </span>
        )}
      </div>
    </div>
  );
}

// -- Transacciones table con expandable rows --------------------------------
function TransaccionesTable({ transacciones }) {
  const [expandedRows, setExpandedRows] = useState(new Set());

  if (!transacciones || transacciones.length === 0) {
    return (
      <div className={styles.emptyState}>Sin transacciones para este cliente</div>
    );
  }

  const toggleExpand = (ctTransaction) => {
    const next = new Set(expandedRows);
    if (next.has(ctTransaction)) {
      next.delete(ctTransaction);
    } else {
      next.add(ctTransaction);
    }
    setExpandedRows(next);
  };

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.thExpand}></th>
            <th>Fecha</th>
            <th>Documento</th>
            <th>Total</th>
            <th>Proveedor</th>
            <th>Items</th>
          </tr>
        </thead>
        <tbody>
          {transacciones.map((tx) => {
            const isExpanded = expandedRows.has(tx.ct_transaction);
            const activeLineas = (tx.lineas || []).filter((l) => !l.cancelled);
            const totalSeriales = activeLineas.reduce(
              (sum, l) => sum + (l.seriales?.length || 0),
              0
            );

            return (
              <Fragment key={tx.ct_transaction}>
                <tr
                  className={`${styles.row} ${styles.rowClickable} ${isExpanded ? styles.rowExpanded : ''}`}
                  onClick={() => toggleExpand(tx.ct_transaction)}
                >
                  <td className={styles.tdExpand}>
                    <ChevronRight
                      size={14}
                      className={`${styles.expandIcon} ${isExpanded ? styles.expandIconOpen : ''}`}
                    />
                  </td>
                  <td>{formatFecha(tx.fecha)}</td>
                  <td className={styles.monoCell}>{tx.nro_documento || '\u2014'}</td>
                  <td className={styles.totalCell}>
                    {tx.total != null ? formatPrecio(tx.total) : '\u2014'}
                  </td>
                  <td>{tx.proveedor || '\u2014'}</td>
                  <td>
                    <span className={styles.countBadge}>
                      <Package size={11} /> {activeLineas.length}
                    </span>
                    {totalSeriales > 0 && (
                      <span className={styles.countBadge}>
                        <ScanBarcode size={11} /> {totalSeriales}
                      </span>
                    )}
                  </td>
                </tr>

                {/* Expanded: line items + serials */}
                {isExpanded && (
                  <tr className={styles.expandedRow}>
                    <td colSpan={6}>
                      {activeLineas.length === 0 ? (
                        <div className={styles.expandedEmpty}>Sin lineas de producto</div>
                      ) : (
                        <div className={styles.expandedContent}>
                          {activeLineas.map((linea) => (
                            <div key={linea.it_transaction} className={styles.lineaRow}>
                              <div className={styles.lineaMain}>
                                {linea.item_code && (
                                  <span className={styles.itemCode}>{linea.item_code}</span>
                                )}
                                <span className={styles.itemDesc}>
                                  {linea.item_desc || '\u2014'}
                                </span>
                                <span className={styles.itemQty}>
                                  x{linea.cantidad ?? 0}
                                </span>
                                {linea.precio_unitario != null && (
                                  <span className={styles.itemPrice}>
                                    {formatPrecio(linea.precio_unitario)}
                                  </span>
                                )}
                              </div>

                              {/* Seriales de esta linea */}
                              {linea.seriales && linea.seriales.length > 0 && (
                                <div className={styles.serialesList}>
                                  {linea.seriales.map((s) => (
                                    <span
                                      key={s.is_serial}
                                      className={`${styles.serialBadge} ${s.is_available ? styles.serialOk : styles.serialNo}`}
                                    >
                                      <ScanBarcode size={10} />
                                      {s.is_serial}
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// -- Pedidos activos (sale orders) -------------------------------------------
function PedidosSection({ pedidos }) {
  const [expandedRows, setExpandedRows] = useState(new Set());

  if (!pedidos || pedidos.length === 0) return null;

  const toggleExpand = (sohId) => {
    const next = new Set(expandedRows);
    if (next.has(sohId)) {
      next.delete(sohId);
    } else {
      next.add(sohId);
    }
    setExpandedRows(next);
  };

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.thExpand}></th>
            <th>Fecha</th>
            <th>Pedido</th>
            <th>Estado</th>
            <th>Total</th>
            <th>Entrega</th>
            <th>ML</th>
          </tr>
        </thead>
        <tbody>
          {pedidos.map((p) => {
            const isExpanded = expandedRows.has(p.soh_id);
            const allSeriales = (p.lineas || []).flatMap((l) => l.seriales || []);

            return (
              <Fragment key={p.soh_id}>
                <tr
                  className={`${styles.row} ${styles.rowClickable} ${isExpanded ? styles.rowExpanded : ''}`}
                  onClick={() => toggleExpand(p.soh_id)}
                >
                  <td className={styles.tdExpand}>
                    <ChevronRight
                      size={14}
                      className={`${styles.expandIcon} ${isExpanded ? styles.expandIconOpen : ''}`}
                    />
                  </td>
                  <td>{formatFecha(p.fecha)}</td>
                  <td className={styles.monoCell}>#{p.soh_id}</td>
                  <td>
                    {p.estado && (
                      <span className={styles.estadoBadge}>{p.estado}</span>
                    )}
                  </td>
                  <td className={styles.totalCell}>
                    {p.total != null ? formatPrecio(p.total) : '\u2014'}
                  </td>
                  <td>{formatFecha(p.fecha_entrega)}</td>
                  <td>
                    {p.ml_id && (
                      <a
                        href={`https://www.mercadolibre.com.ar/ventas/${p.ml_id}/detalle`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.mlLink}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p.ml_id}
                      </a>
                    )}
                  </td>
                </tr>

                {/* Expanded: line items + serials */}
                {isExpanded && (
                  <tr className={styles.expandedRow}>
                    <td colSpan={7}>
                      {(!p.lineas || p.lineas.length === 0) ? (
                        <div className={styles.expandedEmpty}>Sin lineas de producto</div>
                      ) : (
                        <div className={styles.expandedContent}>
                          {p.lineas.map((linea) => (
                            <div key={linea.sod_id} className={styles.lineaRow}>
                              <div className={styles.lineaMain}>
                                {linea.item_code && (
                                  <span className={styles.itemCode}>{linea.item_code}</span>
                                )}
                                <span className={styles.itemDesc}>
                                  {linea.item_desc || '\u2014'}
                                </span>
                                <span className={styles.itemQty}>
                                  x{linea.cantidad ?? 0}
                                </span>
                                {linea.precio_unitario != null && (
                                  <span className={styles.itemPrice}>
                                    {formatPrecio(linea.precio_unitario)}
                                  </span>
                                )}
                              </div>
                            </div>
                          ))}

                          {/* Seriales del pedido */}
                          {allSeriales.length > 0 && (
                            <div className={styles.serialesList}>
                              {allSeriales.map((s) => (
                                <span
                                  key={s.is_serial}
                                  className={`${styles.serialBadge} ${s.is_available ? styles.serialOk : styles.serialNo}`}
                                >
                                  <ScanBarcode size={10} />
                                  {s.is_serial}
                                </span>
                              ))}
                            </div>
                          )}

                          {p.observacion && (
                            <div className={styles.pedidoObs}>{p.observacion}</div>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// -- RMAs del ERP (GBP) -----------------------------------------------------
function RmasErpSection({ rmas }) {
  if (!rmas || rmas.length === 0) return null;

  return (
    <div className={styles.rmaList}>
      {rmas.map((rma) => (
        <div key={`${rma.rmah_id}-${rma.rmad_id}`} className={styles.rmaCard}>
          <div className={styles.rmaCardHeader}>
            <span className={styles.rmaBadge}>RMA #{rma.rmah_id}</span>
            <span className={styles.rmaLine}>Linea #{rma.rmad_id}</span>
            {rma.en_proveedor && (
              <span className={styles.enProveedorBadge}>En proveedor</span>
            )}
          </div>
          <div className={styles.rmaCardBody}>
            <div className={styles.lineaMain}>
              {rma.item_codigo && (
                <span className={styles.itemCode}>{rma.item_codigo}</span>
              )}
              <span className={styles.itemDesc}>{rma.item_descripcion || '\u2014'}</span>
              {rma.serial && (
                <span className={styles.serialBadgeInline}>
                  <ScanBarcode size={10} /> {rma.serial}
                </span>
              )}
              {rma.cantidad != null && (
                <span className={styles.itemQty}>x{rma.cantidad}</span>
              )}
              {rma.precio_original != null && (
                <span className={styles.itemPrice}>{formatPrecio(rma.precio_original)}</span>
              )}
            </div>
            <div className={styles.rmaMetaRow}>
              {rma.fecha_rma && (
                <span className={styles.metaItem}>
                  <Calendar size={11} /> {formatFecha(rma.fecha_rma)}
                </span>
              )}
              {rma.proveedor && (
                <span className={styles.metaItem}>Prov: {rma.proveedor}</span>
              )}
              {rma.deposito && (
                <span className={styles.metaItem}>Dep: {rma.deposito}</span>
              )}
            </div>
            {/* Etapas timeline */}
            {(rma.fecha_recepcion || rma.fecha_diagnostico || rma.fecha_procesamiento || rma.fecha_entrega) && (
              <div className={styles.rmaEtapas}>
                {rma.fecha_recepcion && (
                  <span className={styles.etapaChip}>Recepcion {formatFecha(rma.fecha_recepcion)}</span>
                )}
                {rma.fecha_diagnostico && (
                  <span className={styles.etapaChip}>Diagnostico {formatFecha(rma.fecha_diagnostico)}</span>
                )}
                {rma.fecha_procesamiento && (
                  <span className={styles.etapaChip}>Proceso {formatFecha(rma.fecha_procesamiento)}</span>
                )}
                {rma.fecha_entrega && (
                  <span className={styles.etapaChip}>Entrega {formatFecha(rma.fecha_entrega)}</span>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// -- RMAs internos (rma_casos) -----------------------------------------------
function RmasInternosSection({ casos }) {
  const [expandedCasos, setExpandedCasos] = useState(new Set());

  if (!casos || casos.length === 0) return null;

  const toggleCaso = (casoId) => {
    const next = new Set(expandedCasos);
    if (next.has(casoId)) {
      next.delete(casoId);
    } else {
      next.add(casoId);
    }
    setExpandedCasos(next);
  };

  return (
    <div className={styles.rmaList}>
      {casos.map((caso) => {
        const isExpanded = expandedCasos.has(caso.id);

        return (
          <div key={caso.id} className={styles.rmaCasoCard}>
            <div
              className={styles.rmaCasoHeader}
              onClick={() => toggleCaso(caso.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') toggleCaso(caso.id); }}
            >
              <ChevronRight
                size={14}
                className={`${styles.expandIcon} ${isExpanded ? styles.expandIconOpen : ''}`}
              />
              <span className={styles.rmaBadge}>{caso.numero_caso}</span>
              {caso.estado && (
                <span className={`${styles.casoEstadoBadge} ${caso.estado === 'abierto' ? styles.casoAbierto : styles.casoCerrado}`}>
                  {caso.estado}
                </span>
              )}
              {caso.origen && (
                <span className={styles.casoOrigen}>{caso.origen}</span>
              )}
              {caso.fecha_caso && (
                <span className={styles.metaItem}>
                  <Calendar size={11} /> {formatFecha(caso.fecha_caso)}
                </span>
              )}
              {caso.ml_id && (
                <a
                  href={`https://www.mercadolibre.com.ar/ventas/${caso.ml_id}/detalle`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.mlLink}
                  onClick={(e) => e.stopPropagation()}
                >
                  ML: {caso.ml_id}
                </a>
              )}
            </div>

            {isExpanded && (
              <div className={styles.rmaCasoBody}>
                {/* Meta info */}
                <div className={styles.rmaMetaRow}>
                  {caso.estado_reclamo_ml && (
                    <span className={styles.metaItem}>Reclamo ML: {caso.estado_reclamo_ml}</span>
                  )}
                  {caso.cobertura_ml && (
                    <span className={styles.metaItem}>Cobertura: {caso.cobertura_ml}</span>
                  )}
                  {caso.monto_cubierto != null && (
                    <span className={styles.metaItem}>Monto: {formatPrecio(caso.monto_cubierto)}</span>
                  )}
                </div>

                {caso.observaciones && (
                  <div className={styles.pedidoObs}>{caso.observaciones}</div>
                )}

                {/* Items del caso */}
                {caso.items && caso.items.length > 0 && (
                  <div className={styles.casoItemsList}>
                    {caso.items.map((item) => (
                      <div key={item.id} className={styles.casoItemRow}>
                        <div className={styles.lineaMain}>
                          {item.serial_number && (
                            <span className={styles.serialBadgeInline}>
                              <ScanBarcode size={10} /> {item.serial_number}
                            </span>
                          )}
                          <span className={styles.itemDesc}>{item.producto_desc || '\u2014'}</span>
                          {item.precio != null && (
                            <span className={styles.itemPrice}>{formatPrecio(item.precio)}</span>
                          )}
                        </div>
                        <div className={styles.rmaMetaRow}>
                          {item.estado_recepcion && (
                            <span className={styles.etapaChip}>Recep: {item.estado_recepcion}</span>
                          )}
                          {item.causa_devolucion && (
                            <span className={styles.etapaChip}>Causa: {item.causa_devolucion}</span>
                          )}
                          {item.apto_venta && (
                            <span className={styles.etapaChip}>Apto: {item.apto_venta}</span>
                          )}
                          {item.estado_revision && (
                            <span className={styles.etapaChip}>Revision: {item.estado_revision}</span>
                          )}
                          {item.estado_proceso && (
                            <span className={styles.etapaChip}>Proceso: {item.estado_proceso}</span>
                          )}
                          {item.estado_proveedor && (
                            <span className={styles.etapaChip}>Prov: {item.estado_proveedor}</span>
                          )}
                          {item.proveedor_nombre && (
                            <span className={styles.metaItem}>Proveedor: {item.proveedor_nombre}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// -- Paginacion simple -------------------------------------------------------
function Paginacion({ page, pageSize, total, onPageChange }) {
  if (total <= pageSize) return null;

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div className={styles.paginacion}>
      <span className={styles.pageInfo}>
        Mostrando {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} de{' '}
        {total}
      </span>
      <div className={styles.pageButtons}>
        <button
          className={styles.pageBtn}
          onClick={() => onPageChange(1)}
          disabled={page <= 1}
          aria-label="Primera pagina"
        >
          <ChevronsLeft size={14} />
        </button>
        <button
          className={styles.pageBtn}
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Pagina anterior"
        >
          <ChevronLeft size={14} />
        </button>
        <span className={styles.currentPage}>
          {page} / {totalPages}
        </span>
        <button
          className={styles.pageBtn}
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          aria-label="Pagina siguiente"
        >
          <ChevronRight size={14} />
        </button>
        <button
          className={styles.pageBtn}
          onClick={() => onPageChange(totalPages)}
          disabled={page >= totalPages}
          aria-label="Ultima pagina"
        >
          <ChevronsRight size={14} />
        </button>
      </div>
    </div>
  );
}

// -- Main component ----------------------------------------------------------
export default function TrazaClienteViewer({
  data,
  page = 1,
  pageSize = 50,
  onPageChange,
  compact = false,
}) {
  if (!data) return null;

  const {
    cliente,
    transacciones = [],
    total_transacciones = 0,
    pedidos = [],
    rmas_erp = [],
    rmas_internos = [],
    busqueda_por,
  } = data;

  const hasActivity = total_transacciones > 0 || pedidos.length > 0 ||
    rmas_erp.length > 0 || rmas_internos.length > 0;

  return (
    <div className={`${styles.container} ${compact ? styles.compact : ''}`}>
      {busqueda_por && (
        <div className={styles.searchInfo}>
          Resultado encontrado por:{' '}
          <strong>
            {busqueda_por === 'cust_id' && '# Cliente'}
            {busqueda_por === 'taxnumber' && 'DNI/CUIT'}
            {busqueda_por === 'ml_nickname' && 'Usuario ML'}
            {busqueda_por === 'ml_fallback' && 'Usuario ML (fallback)'}
          </strong>
        </div>
      )}

      {/* Client header always shown — even with no activity */}
      <ClienteHeader cliente={cliente} />

      {!hasActivity && (
        <div className={styles.emptyState}>
          El cliente existe en la base de datos pero no tiene actividad registrada
        </div>
      )}

      {/* Pedidos activos (sale orders) — shown first since they're active */}
      {pedidos.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <ShoppingCart size={14} />
            <span>Pedidos activos ({pedidos.length})</span>
          </div>
          <PedidosSection pedidos={pedidos} />
        </div>
      )}

      {/* RMAs internos (rma_casos) — before transacciones, they're operationally important */}
      {rmas_internos.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <Wrench size={14} />
            <span>Casos RMA ({rmas_internos.length})</span>
          </div>
          <RmasInternosSection casos={rmas_internos} />
        </div>
      )}

      {/* RMAs del ERP (GBP) */}
      {rmas_erp.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <AlertTriangle size={14} />
            <span>RMAs ERP ({rmas_erp.length})</span>
          </div>
          <RmasErpSection rmas={rmas_erp} />
        </div>
      )}

      {/* Transacciones (facturas/NC) — at the bottom since they're historical */}
      {total_transacciones > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <FileText size={14} />
            <span>Transacciones ({total_transacciones})</span>
          </div>
          <TransaccionesTable transacciones={transacciones} />
        </div>
      )}

      {onPageChange && (
        <Paginacion
          page={page}
          pageSize={pageSize}
          total={total_transacciones}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}
