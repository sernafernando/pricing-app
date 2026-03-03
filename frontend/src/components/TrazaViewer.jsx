/**
 * TrazaViewer — Componente reutilizable de traza unificada.
 *
 * Renderiza la historia completa de un serial / venta ML / factura:
 * - Artículo identificado
 * - Movimientos (compra, venta, transferencia) con filas expandibles → detalle de factura
 * - Pedidos vinculados
 * - RMAs del ERP
 * - (futuro) Casos de seguimiento propios
 *
 * Props:
 *   data          — objeto de respuesta de /seriales/traza/{serial} o /seriales/traza/ml/{ml_id}
 *   variant       — "serial" | "ml" | "factura" (controla qué secciones mostrar)
 *   compact       — boolean, si es true reduce padding (para uso en modales)
 */

import { useState, Fragment } from 'react';
import { ChevronRight, Package, FileText, ArrowRightLeft, Truck, AlertTriangle, User, Calendar } from 'lucide-react';
import api from '../services/api';
import styles from './TrazaViewer.module.css';

const TIPO_ICONS = {
  PROVEEDOR: Truck,
  CLIENTE: User,
  TRANSFERENCIA: ArrowRightLeft,
};

const TIPO_LABELS = {
  PROVEEDOR: 'Compra',
  CLIENTE: 'Venta',
  TRANSFERENCIA: 'Transferencia',
};

function formatFecha(fecha) {
  if (!fecha) return '—';
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

// Derives current serial status from last movement
function getEstadoSerial(movimientos) {
  if (!movimientos || movimientos.length === 0) return null;
  const last = movimientos[movimientos.length - 1];
  return last.estado || null;
}

// ── Sección: Artículo identificado + estado del serial ──────────
function ArticuloSection({ articulo, estado }) {
  if (!articulo && !estado) return null;
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <Package size={14} />
        <span>Artículo identificado</span>
        {estado && (
          <span className={`${styles.estadoBadge} ${estado === 'Disponible' ? styles.estadoOk : styles.estadoNo}`}>
            {estado}
          </span>
        )}
      </div>
      {articulo && (
        <div className={styles.articuloCard}>
          <strong>{articulo.descripcion}</strong>
          <div className={styles.articuloMeta}>
            <span className={styles.codeBadge}>{articulo.codigo}</span>
            {articulo.marca && <span className={styles.metaItem}>{articulo.marca}</span>}
            {articulo.categoria && <span className={styles.metaItem}>{articulo.categoria}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Sección: Movimientos con expandable rows ────────────────────
function MovimientosSection({ movimientos }) {
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [rowItems, setRowItems] = useState({});

  if (!movimientos || movimientos.length === 0) return null;

  const toggleExpanded = async (ctTransaction) => {
    if (!ctTransaction) return;

    const newExpanded = new Set(expandedRows);

    if (newExpanded.has(ctTransaction)) {
      newExpanded.delete(ctTransaction);
      setExpandedRows(newExpanded);
      return;
    }

    newExpanded.add(ctTransaction);
    setExpandedRows(newExpanded);

    // Lazy load detail if not already loaded
    if (!rowItems[ctTransaction]) {
      setRowItems((prev) => ({ ...prev, [ctTransaction]: 'loading' }));
      try {
        const { data } = await api.get(`/seriales/traza/factura-detalle/${ctTransaction}`);
        setRowItems((prev) => ({ ...prev, [ctTransaction]: data.items }));
      } catch {
        setRowItems((prev) => ({ ...prev, [ctTransaction]: 'error' }));
      }
    }
  };

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <FileText size={14} />
        <span>Movimientos ({movimientos.length})</span>
      </div>
      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.thExpand}></th>
              <th>Fecha</th>
              <th>Tipo</th>
              <th>Documento</th>
              <th>Referencia</th>
              <th>Depósito</th>
              <th>Días</th>
            </tr>
          </thead>
          <tbody>
            {movimientos.map((mov) => {
              const TipoIcon = TIPO_ICONS[mov.tipo] || FileText;
              const tipoLabel = TIPO_LABELS[mov.tipo] || mov.tipo || '—';
              const isExpanded = expandedRows.has(mov.ct_transaction);
              const items = rowItems[mov.ct_transaction];
              const canExpand = !!mov.ct_transaction;

              return (
                <Fragment key={mov.is_id}>
                  <tr
                    className={`${styles.row} ${canExpand ? styles.rowClickable : ''} ${isExpanded ? styles.rowExpanded : ''}`}
                    onClick={() => canExpand && toggleExpanded(mov.ct_transaction)}
                  >
                    <td className={styles.tdExpand}>
                      {canExpand && (
                        <ChevronRight
                          size={14}
                          className={`${styles.expandIcon} ${isExpanded ? styles.expandIconOpen : ''}`}
                        />
                      )}
                    </td>
                    <td>{formatFecha(mov.fecha_documento)}</td>
                    <td>
                      <span className={`${styles.tipoBadge} ${styles[`tipo${mov.tipo}`] || ''}`}>
                        <TipoIcon size={12} />
                        {tipoLabel}
                      </span>
                    </td>
                    <td className={styles.monoCell}>{mov.nro_documento || '—'}</td>
                    <td>{mov.referencia_nombre || '—'}</td>
                    <td>{mov.deposito || '—'}</td>
                    <td className={styles.diasCell}>{mov.dias_a_la_fecha ?? '—'}</td>
                  </tr>

                  {/* Expanded row — invoice line items */}
                  {isExpanded && (
                    <tr className={styles.expandedRow}>
                      <td colSpan={7}>
                        {items === 'loading' && (
                          <div className={styles.expandedLoading}>Cargando detalle de factura...</div>
                        )}
                        {items === 'error' && (
                          <div className={styles.expandedEmpty}>Error cargando detalle</div>
                        )}
                        {Array.isArray(items) && items.length === 0 && (
                          <div className={styles.expandedEmpty}>Sin líneas de producto</div>
                        )}
                        {Array.isArray(items) && items.length > 0 && (
                          <div className={styles.expandedContent}>
                            <div className={styles.itemsList}>
                              {items.filter((item) => !item.cancelled).map((item) => (
                                <div key={item.it_transaction} className={styles.itemRow}>
                                  {item.item_code && (
                                    <span className={styles.itemCode}>{item.item_code}</span>
                                  )}
                                  <span className={styles.itemDesc}>{item.item_desc || '—'}</span>
                                  <span className={styles.itemQty}>x{item.cantidad ?? 0}</span>
                                  {item.precio_unitario != null && (
                                    <span className={styles.itemPrice}>
                                      {formatPrecio(item.precio_unitario)}
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
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
    </div>
  );
}

// ── Sección: Pedidos ────────────────────────────────────────────
function PedidosSection({ pedidos }) {
  if (!pedidos || pedidos.length === 0) return null;
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <Truck size={14} />
        <span>Pedidos ({pedidos.length})</span>
      </div>
      <div className={styles.pedidosList}>
        {pedidos.map((p) => (
          <div key={p.soh_id} className={styles.pedidoCard}>
            <div className={styles.pedidoMain}>
              <span className={styles.codeBadge}>#{p.soh_id}</span>
              {p.cliente && <span>{p.cliente}</span>}
              {p.estado && (
                <span className={styles.estadoBadge}>{p.estado}</span>
              )}
            </div>
            <div className={styles.pedidoMeta}>
              {p.fecha && (
                <span className={styles.metaItem}>
                  <Calendar size={11} /> {formatFecha(p.fecha)}
                </span>
              )}
              {p.ml_id && (
                <a
                  href={`https://www.mercadolibre.com.ar/ventas/${p.ml_id}/detalle`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.mlLink}
                >
                  ML: {p.ml_id}
                </a>
              )}
              {p.shipping_id && (
                <span className={styles.metaItem}>Envío: {p.shipping_id}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Sección: RMAs ───────────────────────────────────────────────
function RmasSection({ rmaList, title = 'RMAs del ERP' }) {
  if (!rmaList || rmaList.length === 0) return null;
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <AlertTriangle size={14} />
        <span>{title} ({rmaList.length})</span>
      </div>
      <div className={styles.rmaList}>
        {rmaList.map((rma) => (
          <div key={`${rma.rmah_id}-${rma.rmad_id}`} className={styles.rmaCard}>
            <div className={styles.rmaHeader}>
              <span className={styles.codeBadge}>RMA #{rma.rmah_id}</span>
              <span className={styles.metaItem}>Línea #{rma.rmad_id}</span>
              <span className={`${styles.matchBadge} ${styles[`match${rma.match_por}`] || ''}`}>
                {rma.match_por}
              </span>
            </div>
            <div className={styles.rmaBody}>
              {rma.item_descripcion && (
                <div className={styles.rmaProduct}>
                  {rma.item_codigo && <span className={styles.codeBadge}>{rma.item_codigo}</span>}
                  <span>{rma.item_descripcion}</span>
                  {rma.cantidad != null && <span className={styles.itemQty}>x{rma.cantidad}</span>}
                </div>
              )}
              <div className={styles.rmaMeta}>
                {rma.fecha_rma && (
                  <span className={styles.metaItem}>
                    <Calendar size={11} /> {formatFecha(rma.fecha_rma)}
                  </span>
                )}
                {rma.cliente && <span className={styles.metaItem}>Cliente: {rma.cliente}</span>}
                {rma.proveedor && <span className={styles.metaItem}>Proveedor: {rma.proveedor}</span>}
                {rma.precio_original != null && (
                  <span className={styles.metaItem}>{formatPrecio(rma.precio_original)}</span>
                )}
              </div>
              {rma.historial && rma.historial.length > 0 && (
                <div className={styles.rmaHistorial}>
                  {rma.historial.map((h) => (
                    <span key={h.rmadh_id} className={styles.histStep}>
                      {formatFecha(h.fecha)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────
export default function TrazaViewer({ data, variant = 'serial', compact = false }) {
  if (!data) return null;

  // Normalize data based on variant
  const serial = variant === 'serial' ? data.serial : null;
  const articulo = data.articulo || null;
  const movimientos = data.movimientos || [];
  const pedidos = data.pedidos || [];
  const rma = data.rma || [];
  const rma_por_factura = data.rma_por_factura || [];

  // ML variant: data has seriales[] array (multiple serials per sale)
  const seriales = data.seriales || [];

  const hasContent = articulo || movimientos.length > 0 || pedidos.length > 0 ||
    rma.length > 0 || rma_por_factura.length > 0 || seriales.length > 0;

  if (!hasContent) {
    return (
      <div className={`${styles.container} ${compact ? styles.compact : ''}`}>
        <div className={styles.emptyState}>Sin resultados de traza</div>
      </div>
    );
  }

  return (
    <div className={`${styles.container} ${compact ? styles.compact : ''}`}>
      {/* Serial header */}
      {serial && (
        <div className={styles.serialHeader}>
          Serial: <strong>{serial}</strong>
        </div>
      )}

      {/* Single serial variant */}
      {variant === 'serial' && (
        <>
          <ArticuloSection articulo={articulo} estado={getEstadoSerial(movimientos)} />
          <MovimientosSection movimientos={movimientos} />
          <PedidosSection pedidos={pedidos} />
          <RmasSection rmaList={rma} title="RMAs del ERP (por serial)" />
        </>
      )}

      {/* ML variant: shows pedidos first, then each serial's trace */}
      {variant === 'ml' && (
        <>
          {data.busqueda_por && (
            <div className={styles.serialHeader}>
              ML ID: <strong>{data.ml_id}</strong>
              <span className={styles.metaItem}>({data.busqueda_por})</span>
            </div>
          )}
          <PedidosSection pedidos={pedidos} />
          {seriales.map((s) => (
            <div key={s.serial} className={styles.serialBlock}>
              <div className={styles.serialSubheader}>
                Serial: <strong>{s.serial}</strong>
              </div>
              <ArticuloSection articulo={s.articulo} estado={getEstadoSerial(s.movimientos)} />
              <MovimientosSection movimientos={s.movimientos} />
              <RmasSection rmaList={s.rma} title="RMAs (por serial)" />
            </div>
          ))}
          <RmasSection rmaList={rma_por_factura} title="RMAs (por factura)" />
        </>
      )}

      {/* Factura variant */}
      {variant === 'factura' && (
        <>
          {data.factura && (
            <div className={styles.facturaHeader}>
              <div className={styles.facturaMain}>
                <span className={styles.codeBadge}>
                  {data.factura.tipo} {String(data.factura.punto_venta).padStart(4, '0')}-{data.factura.nro_documento}
                </span>
                {data.factura.fecha && <span>{formatFecha(data.factura.fecha)}</span>}
                {data.factura.total != null && (
                  <strong>{formatPrecio(data.factura.total)}</strong>
                )}
              </div>
              <div className={styles.facturaMeta}>
                {data.factura.cliente && <span>Cliente: {data.factura.cliente}</span>}
                {data.factura.proveedor && <span>Proveedor: {data.factura.proveedor}</span>}
              </div>
            </div>
          )}
          {seriales.map((s) => (
            <div key={s.serial} className={styles.serialBlock}>
              <div className={styles.serialSubheader}>
                Serial: <strong>{s.serial}</strong>
              </div>
              <ArticuloSection articulo={s.articulo} estado={getEstadoSerial(s.movimientos)} />
              <MovimientosSection movimientos={s.movimientos} />
              <RmasSection rmaList={s.rma} title="RMAs (por serial)" />
            </div>
          ))}
          <RmasSection rmaList={data.rma_por_serial} title="RMAs (por serial)" />
          <RmasSection rmaList={rma_por_factura} title="RMAs (por factura)" />
        </>
      )}
    </div>
  );
}
