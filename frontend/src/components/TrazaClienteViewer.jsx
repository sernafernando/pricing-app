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
  ScanBarcode,
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
    busqueda_por,
  } = data;

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

      <ClienteHeader cliente={cliente} />

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

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <FileText size={14} />
          <span>Transacciones ({total_transacciones})</span>
        </div>
        <TransaccionesTable transacciones={transacciones} />
      </div>

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
