import { useCallback, useEffect, useState } from 'react';
import {
  Loader2,
  Layers,
  List,
  ChevronDown,
  ChevronRight,
  Plus,
  Zap,
  Sliders,
  Eye,
  FileText,
  Receipt,
  X,
  ArrowDownToLine,
  ArrowUpFromLine,
  Wallet,
  Search as SearchIcon,
  Inbox,
  Coins,
} from 'lucide-react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import useCCProveedor from '../../hooks/useCCProveedor';
import ModalOrdenPagoNueva from './ModalOrdenPagoNueva';
import ModalPedidoCompra from './ModalPedidoCompra';
import ModalPedidoDetalle from './ModalPedidoDetalle';
import ModalOrdenPagoDetalle from './ModalOrdenPagoDetalle';
import ModalNCLocal from './ModalNCLocal';
import ModalNCLocalDetalle from './ModalNCLocalDetalle';
import PanelImputaciones from './PanelImputaciones';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './TabCCProveedores.module.css';

const formatMoneda = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoStr;
  }
};

/** Extrae 2 iniciales del nombre del proveedor para el monogram del hero. */
const getInitials = (nombre) => {
  if (!nombre) return '··';
  const cleaned = String(nombre).replace(/[^A-Za-zÀ-ÿ\s]/g, '').trim();
  if (!cleaned) return '··';
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

/**
 * Calcula running balance por moneda, descomponiendo cada movimiento en
 * Debe / Haber. Convención libro mayor:
 *  - tipo='debe'                          → suma a Debe (incrementa deuda)
 *  - tipo='haber'                         → suma a Haber (paga deuda)
 *  - tipo='ajuste' con signo_ajuste=+1    → suma a Debe
 *  - tipo='ajuste' con signo_ajuste=-1    → suma a Haber
 *
 * Devuelve cada movimiento enriquecido con { debe, haber, saldoCorriente }.
 * El saldo es por moneda — sumar ARS y USD juntos no tiene sentido.
 */
const enriquecerConDebeHaberYSaldo = (movimientos = []) => {
  const saldosPorMoneda = {};
  return movimientos.map((m) => {
    const monto = Number(m.monto) || 0;
    let debe = 0;
    let haber = 0;
    if (m.tipo === 'debe') {
      debe = monto;
    } else if (m.tipo === 'haber') {
      haber = monto;
    } else if (m.tipo === 'ajuste') {
      if (m.signo_ajuste === 1) debe = monto;
      else if (m.signo_ajuste === -1) haber = monto;
    }
    const prev = saldosPorMoneda[m.moneda] || 0;
    const saldoCorriente = prev + debe - haber;
    saldosPorMoneda[m.moneda] = saldoCorriente;
    return { ...m, debe, haber, saldoCorriente };
  });
};

export default function TabCCProveedores() {
  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  // El objeto `ccApi` se recrea en cada render; las funciones internas son estables.
  const {
    obtenerDetalle,
    obtenerPorPedido,
    loading: ccLoading,
    error: ccError,
  } = useCCProveedor();

  const { tienePermiso } = usePermisos();
  const canGestionar = tienePermiso('administracion.gestionar_ordenes_compra');
  const canEjecutarPagos = tienePermiso('administracion.ejecutar_pagos');
  const canAjustarCcManual = tienePermiso('administracion.ajustar_cc_proveedor_manual');

  // A.6: un solo estado — el autocomplete setea el id activo directamente y
  // dispara fetch inmediato. Ya no hace falta un input "staging" + botón Buscar.
  const [proveedorIdActivo, setProveedorIdActivo] = useState(null);

  const [filtroEmpresa, setFiltroEmpresa] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [view, setView] = useState('cronologico'); // 'cronologico' | 'por-pedido'
  // Sección colapsable de imputaciones (COMPRAS-7.5 refactor UX: se integró
  // acá en vez de vivir como sub-tab de OPs).
  const [mostrarImputaciones, setMostrarImputaciones] = useState(false);

  const [empresas, setEmpresas] = useState([]);

  const [detalle, setDetalle] = useState(null);
  const [porPedido, setPorPedido] = useState([]);
  const [tcEstimado, setTcEstimado] = useState(null);

  // ── Sub-batch 5 — acciones desde el header del proveedor ──
  // proveedorCtx: contexto pre-cargado para los modales que crean entidades.
  const proveedorCtx = detalle
    ? {
        id: detalle.proveedor_id,
        nombre: detalle.nombre_proveedor,
        empresa_id: filtroEmpresa ? Number(filtroEmpresa) : null,
      }
    : null;

  const [showNuevaOP, setShowNuevaOP] = useState(false);
  const [showNuevoPedido, setShowNuevoPedido] = useState(false);
  const [showNuevaNC, setShowNuevaNC] = useState(false);
  const [showPagoRapido, setShowPagoRapido] = useState(false);
  const [showAjusteManual, setShowAjusteManual] = useState(false);

  // Sub-batch 5.D: detalle de movimiento clickeado.
  const [detalleMov, setDetalleMov] = useState(null); // { tipo, id }

  const fetchEmpresas = useCallback(async () => {
    try {
      const { data } = await api.get('/admin/empresas');
      setEmpresas(data || []);
    } catch {
      setEmpresas([]);
    }
  }, []);

  useEffect(() => {
    fetchEmpresas();
  }, [fetchEmpresas]);

  const fetchTcDelDia = useCallback(async () => {
    // No es bloqueante — si no existe el endpoint, dejamos null.
    try {
      const { data } = await api.get('/tipo-cambio/actual');
      if (data?.tipo_cambio) setTcEstimado(Number(data.tipo_cambio));
    } catch {
      setTcEstimado(null);
    }
  }, []);

  useEffect(() => {
    fetchTcDelDia();
  }, [fetchTcDelDia]);

  const fetchDetalle = useCallback(async () => {
    if (!proveedorIdActivo) return;
    const params = {};
    if (filtroEmpresa) params.empresa_id = filtroEmpresa;
    if (filtroHasta) params.hasta_fecha = filtroHasta;
    try {
      const data = await obtenerDetalle(proveedorIdActivo, params);
      setDetalle(data);
    } catch {
      setDetalle(null);
    }
  }, [obtenerDetalle, proveedorIdActivo, filtroEmpresa, filtroHasta]);

  const fetchPorPedido = useCallback(async () => {
    if (!proveedorIdActivo) return;
    try {
      const data = await obtenerPorPedido(proveedorIdActivo);
      setPorPedido(data || []);
    } catch {
      setPorPedido([]);
    }
  }, [obtenerPorPedido, proveedorIdActivo]);

  useEffect(() => {
    if (proveedorIdActivo) {
      fetchDetalle();
      fetchPorPedido();
    }
  }, [proveedorIdActivo, fetchDetalle, fetchPorPedido]);

  useEffect(() => {
    if (proveedorIdActivo) fetchDetalle();
  }, [filtroEmpresa, filtroHasta, fetchDetalle, proveedorIdActivo]);

  const saldos = detalle?.saldos || [];
  const saldoUsd = saldos.find((s) => s.moneda === 'USD')?.saldo || 0;
  const saldoArs = saldos.find((s) => s.moneda === 'ARS')?.saldo || 0;
  const consolidadoArs =
    tcEstimado && Number(saldoUsd) !== 0
      ? Number(saldoArs) + Number(saldoUsd) * tcEstimado
      : null;

  const movsArsCount = saldos.find((s) => s.moneda === 'ARS')?.movimientos_count || 0;
  const movsUsdCount = saldos.find((s) => s.moneda === 'USD')?.movimientos_count || 0;
  const initials = detalle ? getInitials(detalle.nombre_proveedor) : '';

  return (
    <div className={styles.container}>
      {/* ── Search bar (sticky-feel) ───────────────────────────────── */}
      <div className={styles.searchBar}>
        <div className={styles.searchProveedor}>
          <ProveedorComprasAutocomplete
            value={proveedorIdActivo}
            onChange={(id) => setProveedorIdActivo(id || null)}
            placeholder="Buscar proveedor (nombre, CUIT)..."
          />
        </div>
        <select
          className={styles.select}
          value={filtroEmpresa}
          onChange={(e) => setFiltroEmpresa(e.target.value)}
          aria-label="Filtrar por empresa"
        >
          <option value="">Todas las empresas</option>
          {empresas.map((emp) => (
            <option key={emp.id} value={emp.id}>
              {emp.nombre}
            </option>
          ))}
        </select>
        <input
          type="date"
          className={styles.input}
          value={filtroHasta}
          onChange={(e) => setFiltroHasta(e.target.value)}
          title="Hasta fecha"
          aria-label="Filtrar hasta fecha"
        />
      </div>

      {ccError && <div className={styles.errorBanner}>{ccError}</div>}

      {!proveedorIdActivo ? (
        <div className={styles.heroEmpty}>
          <div className={styles.heroEmptyIcon}>
            <SearchIcon size={36} strokeWidth={1.5} />
          </div>
          <div className={styles.heroEmptyTitle}>Buscá un proveedor</div>
          <div className={styles.heroEmptySub}>
            Empezá tipeando el nombre o el CUIT en el buscador. La cuenta corriente
            aparece acá con todos los movimientos al instante.
          </div>
        </div>
      ) : ccLoading && !detalle ? (
        <div className={styles.heroLoading}>
          <Loader2 size={28} className={styles.spin} strokeWidth={1.8} />
          <div className={styles.heroLoadingText}>Cargando cuenta corriente…</div>
        </div>
      ) : !detalle ? (
        <div className={styles.heroEmpty}>
          <div className={styles.heroEmptyIcon}>
            <Inbox size={36} strokeWidth={1.5} />
          </div>
          <div className={styles.heroEmptyTitle}>Sin datos</div>
          <div className={styles.heroEmptySub}>
            No encontramos información para este proveedor con los filtros actuales.
          </div>
        </div>
      ) : (
        <>
          {/* ── HERO: identidad del proveedor + saldos como métricas ── */}
          <section className={styles.hero}>
            <div className={styles.heroIdentity}>
              <div className={styles.monogram} aria-hidden="true">
                {initials}
              </div>
              <div className={styles.heroIdentityText}>
                <h2 className={styles.proveedorNombre}>
                  {detalle.nombre_proveedor || `Proveedor #${detalle.proveedor_id}`}
                </h2>
                <div className={styles.heroIdentityMeta}>
                  <span className={styles.proveedorId}>#{detalle.proveedor_id}</span>
                  {filtroEmpresa && (
                    <span className={styles.heroChip}>
                      {empresas.find((e) => String(e.id) === filtroEmpresa)?.nombre || 'Empresa'}
                    </span>
                  )}
                  {filtroHasta && (
                    <span className={styles.heroChip}>hasta {formatDate(filtroHasta)}</span>
                  )}
                </div>
              </div>
            </div>

            <div className={styles.metrics}>
              <MetricTile
                label="Saldo ARS"
                value={formatMoneda(saldoArs, 'ARS')}
                hint={`${movsArsCount} movimientos`}
                tone={Number(saldoArs) > 0 ? 'debe' : Number(saldoArs) < 0 ? 'haber' : 'neutral'}
              />
              <MetricTile
                label="Saldo USD"
                value={formatMoneda(saldoUsd, 'USD')}
                hint={`${movsUsdCount} movimientos`}
                tone={Number(saldoUsd) > 0 ? 'debe' : Number(saldoUsd) < 0 ? 'haber' : 'neutral'}
              />
              <MetricTile
                label="Consolidado ARS"
                value={consolidadoArs !== null ? formatMoneda(consolidadoArs, 'ARS') : '—'}
                hint={consolidadoArs !== null ? 'Estimado · TC del día' : 'TC no disponible'}
                tone="estimate"
              />
            </div>
          </section>

          {/* ── Quick actions (chips) ──────────────────────────────── */}
          <div className={styles.accionesBar} role="toolbar" aria-label="Acciones rápidas">
            {canGestionar && (
              <button
                type="button"
                className={styles.actionChip}
                onClick={() => setShowNuevoPedido(true)}
                title="Crear pedido pre-cargado con este proveedor"
              >
                <Plus size={13} /> Nuevo pedido
              </button>
            )}
            {canGestionar && (
              <button
                type="button"
                className={styles.actionChip}
                onClick={() => setShowNuevaOP(true)}
                title="Crear OP pre-cargada con este proveedor"
              >
                <Plus size={13} /> Nueva OP
              </button>
            )}
            {canGestionar && (
              <button
                type="button"
                className={styles.actionChip}
                onClick={() => setShowNuevaNC(true)}
                title="Crear NC local pre-cargada con este proveedor"
              >
                <Plus size={13} /> Nueva NC
              </button>
            )}
            {canEjecutarPagos && (
              <button
                type="button"
                className={`${styles.actionChip} ${styles.actionChipAccent}`}
                onClick={() => setShowPagoRapido(true)}
                title="Crear OP a_cuenta + ejecutar pago en un solo paso"
              >
                <Zap size={13} /> Pago rápido
              </button>
            )}
            {canAjustarCcManual && (
              <button
                type="button"
                className={`${styles.actionChip} ${styles.actionChipDanger}`}
                onClick={() => setShowAjusteManual(true)}
                title="Ajuste manual append-only (permiso crítico)"
              >
                <Sliders size={13} /> Ajuste manual
              </button>
            )}
          </div>

          {/* ── Section title + view switcher ──────────────────────── */}
          <div className={styles.ledgerToolbar}>
            <div className={styles.ledgerTitleBlock}>
              <Wallet size={14} className={styles.ledgerTitleIcon} />
              <span className={styles.ledgerTitle}>Libro mayor</span>
              <span className={styles.ledgerSubtitle}>
                Movimientos {view === 'cronologico' ? 'cronológicos' : 'agrupados por pedido'}
              </span>
            </div>
            <div className={styles.viewSwitcher} role="tablist" aria-label="Vista">
              <button
                role="tab"
                aria-selected={view === 'cronologico'}
                className={view === 'cronologico' ? styles.viewBtnActive : styles.viewBtn}
                onClick={() => setView('cronologico')}
              >
                <List size={13} /> Cronológico
              </button>
              <button
                role="tab"
                aria-selected={view === 'por-pedido'}
                className={view === 'por-pedido' ? styles.viewBtnActive : styles.viewBtn}
                onClick={() => setView('por-pedido')}
              >
                <Layers size={13} /> Por pedido
              </button>
            </div>
          </div>

          {/* Vistas */}
          {view === 'cronologico' ? (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Origen / Descripción</th>
                    <th className={styles.thRight}>Debe</th>
                    <th className={styles.thRight}>Haber</th>
                    <th className={styles.thRight}>Saldo</th>
                    <th>Mon.</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {(detalle.movimientos || []).length === 0 ? (
                    <tr>
                      <td colSpan={7} className={styles.emptyRow}>
                        <div className={styles.emptyRowInner}>
                          <Coins size={28} strokeWidth={1.5} />
                          <span>Sin movimientos en este periodo.</span>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    enriquecerConDebeHaberYSaldo(detalle.movimientos).map((m) => {
                      const navegable =
                        m.origen_id &&
                        ['pedido_compra', 'orden_pago', 'nota_credito_local'].includes(
                          m.origen_tipo
                        );
                      const origenLabel =
                        m.origen_descripcion ||
                        `${m.origen_tipo}${m.origen_id ? ` #${m.origen_id}` : ''}`;
                      return (
                        <tr key={m.id} className={navegable ? styles.rowClickable : undefined}>
                          <td className={styles.tdSecondary}>
                            {formatDate(m.fecha_movimiento)}
                          </td>
                          <td>
                            <div className={styles.origenLine}>
                              <span
                                className={
                                  m.tipo === 'debe'
                                    ? styles.badgeDebe
                                    : m.tipo === 'haber'
                                      ? styles.badgeHaber
                                      : styles.badgeAjuste
                                }
                              >
                                {m.tipo}
                              </span>
                              <span className={styles.origenLabel}>{origenLabel}</span>
                            </div>
                            {m.descripcion && (
                              <div className={styles.tdSecondary}>{m.descripcion}</div>
                            )}
                          </td>
                          <td className={styles.tdRightDebe}>
                            {m.debe > 0 ? formatMoneda(m.debe, m.moneda) : ''}
                          </td>
                          <td className={styles.tdRightHaber}>
                            {m.haber > 0 ? formatMoneda(m.haber, m.moneda) : ''}
                          </td>
                          <td className={styles.tdRightSaldo}>
                            {formatMoneda(m.saldoCorriente, m.moneda)}
                          </td>
                          <td className={styles.tdSecondary}>{m.moneda}</td>
                          <td>
                            {navegable && (
                              <button
                                type="button"
                                className={styles.iconBtn}
                                onClick={() =>
                                  setDetalleMov({ tipo: m.origen_tipo, id: m.origen_id })
                                }
                                aria-label="Ver detalle"
                                title="Ver detalle del documento origen"
                              >
                                <Eye size={14} />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={styles.grupoList}>
              {porPedido.length === 0 ? (
                <div className={styles.emptyBlock}>
                  <Layers size={28} strokeWidth={1.5} />
                  <span>Sin pedidos con movimientos en CC.</span>
                </div>
              ) : (
                porPedido.map((g) => (
                  <div key={g.pedido_compra_id} className={styles.grupoCard}>
                    <div className={styles.grupoHeader}>
                      <div className={styles.grupoHeaderLeft}>
                        <strong className={styles.grupoNumero}>{g.pedido_numero}</strong>
                        <span className={styles.grupoEstado}>{g.pedido_estado}</span>
                      </div>
                      <div className={styles.grupoMonto}>
                        {formatMoneda(g.pedido_monto, g.pedido_moneda)}
                      </div>
                    </div>
                    <div className={styles.grupoMovs}>
                      <div className={`${styles.grupoMovRow} ${styles.grupoMovHeader}`}>
                        <span className={styles.tdSecondary}>Fecha</span>
                        <span className={styles.tdSecondary}>Origen / Desc.</span>
                        <span className={styles.tdSecondaryRight}>Debe</span>
                        <span className={styles.tdSecondaryRight}>Haber</span>
                        <span className={styles.tdSecondaryRight}>Saldo</span>
                        <span />
                      </div>
                      {enriquecerConDebeHaberYSaldo(g.movimientos).map((m) => {
                        const navegable =
                          m.origen_id &&
                          ['pedido_compra', 'orden_pago', 'nota_credito_local'].includes(
                            m.origen_tipo
                          );
                        const origenLabel =
                          m.origen_descripcion ||
                          `${m.origen_tipo}${m.origen_id ? ` #${m.origen_id}` : ''}`;
                        return (
                          <div
                            key={m.id}
                            className={`${styles.grupoMovRow} ${navegable ? styles.rowClickable : ''}`}
                          >
                            <span className={styles.tdSecondary}>
                              {formatDate(m.fecha_movimiento)}
                            </span>
                            <span className={styles.grupoMovDesc} title={m.descripcion || ''}>
                              <span
                                className={
                                  m.tipo === 'debe'
                                    ? styles.badgeDebe
                                    : m.tipo === 'haber'
                                      ? styles.badgeHaber
                                      : styles.badgeAjuste
                                }
                              >
                                {m.tipo}
                              </span>{' '}
                              {origenLabel}
                            </span>
                            <span className={styles.tdRightDebe}>
                              {m.debe > 0 ? formatMoneda(m.debe, m.moneda) : ''}
                            </span>
                            <span className={styles.tdRightHaber}>
                              {m.haber > 0 ? formatMoneda(m.haber, m.moneda) : ''}
                            </span>
                            <span className={styles.tdRightSaldo}>
                              {formatMoneda(m.saldoCorriente, m.moneda)}
                            </span>
                            <span>
                              {navegable && (
                                <button
                                  type="button"
                                  className={styles.iconBtn}
                                  onClick={() =>
                                    setDetalleMov({ tipo: m.origen_tipo, id: m.origen_id })
                                  }
                                  aria-label="Ver detalle"
                                  title="Ver detalle del documento origen"
                                >
                                  <Eye size={14} />
                                </button>
                              )}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Imputaciones del proveedor — colapsable para no saturar. */}
          <details
            className={styles.imputacionesSection}
            open={mostrarImputaciones}
            onToggle={(e) => setMostrarImputaciones(e.currentTarget.open)}
          >
            <summary className={styles.imputacionesToggle}>
              <span className={styles.imputacionesToggleIcon} aria-hidden="true">
                {mostrarImputaciones ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </span>
              <span className={styles.imputacionesToggleLabel}>Imputaciones del proveedor</span>
              <span className={styles.imputacionesToggleHint}>
                origen ↔ destino · trazabilidad completa
              </span>
            </summary>
            {mostrarImputaciones && (
              <div className={styles.imputacionesBody}>
                <PanelImputaciones proveedorIdFijo={proveedorIdActivo} />
              </div>
            )}
          </details>
        </>
      )}

      {/* ── Sub-batch 5.B — Nueva OP pre-cargada ── */}
      {showNuevaOP && proveedorCtx && (
        <ModalOrdenPagoNueva
          empresas={empresas}
          proveedorInicial={proveedorCtx}
          pendientesDelProveedor={[]}
          onClose={(reload) => {
            setShowNuevaOP(false);
            if (reload) fetchDetalle();
          }}
        />
      )}

      {/* ── Sub-batch 5.F — Nuevo pedido pre-cargado ── */}
      {showNuevoPedido && proveedorCtx && (
        <ModalPedidoCompra
          pedido={null}
          empresas={empresas}
          proveedorInicial={proveedorCtx}
          onClose={(reload) => {
            setShowNuevoPedido(false);
            if (reload) fetchDetalle();
          }}
        />
      )}

      {/* ── Sub-batch 5.E — Nueva NC local pre-cargada ── */}
      {showNuevaNC && proveedorCtx && (
        <ModalNCLocal
          nc={null}
          empresas={empresas}
          proveedorInicial={proveedorCtx}
          onClose={(reload) => {
            setShowNuevaNC(false);
            if (reload) fetchDetalle();
          }}
        />
      )}

      {/* ── Sub-batch 5.D — Detalle del movimiento clickeado ── */}
      {detalleMov?.tipo === 'pedido_compra' && (
        <ModalPedidoDetalle
          pedidoId={detalleMov.id}
          onClose={() => setDetalleMov(null)}
        />
      )}
      {detalleMov?.tipo === 'orden_pago' && (
        <ModalOrdenPagoDetalle
          op={{ id: detalleMov.id }}
          onClose={() => setDetalleMov(null)}
        />
      )}
      {detalleMov?.tipo === 'nota_credito_local' && (
        <ModalNCLocalDetalle
          ncId={detalleMov.id}
          onClose={() => setDetalleMov(null)}
        />
      )}

      {/* ── Sub-batch 5.G — Pago rápido ── */}
      {showPagoRapido && proveedorCtx && (
        <ModalPagoRapido
          proveedor={proveedorCtx}
          empresas={empresas}
          onClose={(reload) => {
            setShowPagoRapido(false);
            if (reload) fetchDetalle();
          }}
        />
      )}

      {/* ── Sub-batch 5.H — Ajuste manual CC ── */}
      {showAjusteManual && proveedorCtx && (
        <ModalAjusteCCManual
          proveedor={proveedorCtx}
          empresas={empresas}
          onClose={(reload) => {
            setShowAjusteManual(false);
            if (reload) fetchDetalle();
          }}
        />
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Internal helper components
// ══════════════════════════════════════════════════════════════════════════

function MetricTile({ label, value, hint, tone = 'neutral' }) {
  const toneClass =
    tone === 'debe'
      ? styles.metricTileDebe
      : tone === 'haber'
        ? styles.metricTileHaber
        : tone === 'estimate'
          ? styles.metricTileEstimate
          : styles.metricTileNeutral;
  const Glyph = tone === 'haber' ? ArrowUpFromLine : tone === 'debe' ? ArrowDownToLine : Wallet;
  return (
    <div className={`${styles.metricTile} ${toneClass}`}>
      <div className={styles.metricLabelRow}>
        <Glyph size={12} strokeWidth={2} />
        <span className={styles.metricLabel}>{label}</span>
      </div>
      <div className={styles.metricValue}>{value}</div>
      <div className={styles.metricHint}>{hint}</div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Modales inline del tab CC (sub-batch 5.G + 5.H).
// Se mantienen en este archivo porque son específicos de la UX del tab CC
// (no se reusan desde otros lugares).
// ══════════════════════════════════════════════════════════════════════════

function ModalPagoRapido({ proveedor, empresas, onClose }) {
  const todayIso = () => new Date().toISOString().split('T')[0];
  const [form, setForm] = useState({
    empresa_id: proveedor.empresa_id ? String(proveedor.empresa_id) : '',
    caja_id: '',
    moneda: 'ARS',
    monto: '',
    fecha_pago_real: todayIso(),
    tipo_cambio: '',
    observaciones: '',
  });
  const [cajas, setCajas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get('/administracion-caja/cajas');
        setCajas(data || []);
      } catch {
        setCajas([]);
      }
    })();
  }, []);

  const cajasFiltradas = cajas.filter((c) => {
    if (form.empresa_id && c.empresa_id && String(c.empresa_id) !== form.empresa_id) {
      return false;
    }
    return true;
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.empresa_id) return setError('Empresa requerida.');
    if (!form.caja_id) return setError('Caja requerida.');
    const monto = parseFloat(form.monto);
    if (!Number.isFinite(monto) || monto <= 0) return setError('Monto > 0 requerido.');

    setLoading(true);
    setError(null);
    try {
      const body = {
        empresa_id: Number(form.empresa_id),
        caja_id: Number(form.caja_id),
        moneda: form.moneda,
        monto,
        fecha_pago_real: form.fecha_pago_real,
        observaciones: form.observaciones || null,
      };
      if (form.tipo_cambio) {
        body.tipo_cambio = parseFloat(form.tipo_cambio);
      }
      await api.post(`/administracion/compras/cc-proveedor/${proveedor.id}/pago-rapido`, body);
      onClose(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al ejecutar el pago rápido.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <Zap size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Pago rápido — {proveedor.nombre}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(false)}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </div>
        {error && <div className={styles.errorBanner}>{error}</div>}
        <p className={styles.modalHelp}>
          <Receipt size={12} /> Crea una OP modo <code>a_cuenta</code> + ejecuta el pago
          en un solo paso. Deja trazabilidad completa (número OP, evento,
          caja_movimiento).
        </p>
        <form onSubmit={handleSubmit}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Empresa *</label>
            <select
              className={styles.select}
              value={form.empresa_id}
              onChange={(e) => setForm({ ...form, empresa_id: e.target.value })}
              required
            >
              <option value="">Seleccionar...</option>
              {empresas.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.nombre}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Caja *</label>
            <select
              className={styles.select}
              value={form.caja_id}
              onChange={(e) => setForm({ ...form, caja_id: e.target.value })}
              required
            >
              <option value="">Seleccionar caja...</option>
              {cajasFiltradas.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.nombre} — {c.moneda}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Moneda *</label>
              <select
                className={styles.select}
                value={form.moneda}
                onChange={(e) => setForm({ ...form, moneda: e.target.value })}
              >
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Monto *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className={styles.input}
                value={form.monto}
                onChange={(e) => setForm({ ...form, monto: e.target.value })}
                placeholder="0.00"
                required
              />
            </div>
          </div>
          {form.moneda === 'USD' && (
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Tipo de cambio</label>
              <input
                type="number"
                step="0.0001"
                min="0"
                className={styles.input}
                value={form.tipo_cambio}
                onChange={(e) => setForm({ ...form, tipo_cambio: e.target.value })}
                placeholder="TC al momento del pago"
              />
            </div>
          )}
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Fecha pago real *</label>
            <input
              type="date"
              className={styles.input}
              value={form.fecha_pago_real}
              onChange={(e) => setForm({ ...form, fecha_pago_real: e.target.value })}
              required
            />
          </div>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Observaciones</label>
            <textarea
              className={styles.textarea}
              value={form.observaciones}
              onChange={(e) => setForm({ ...form, observaciones: e.target.value })}
              rows={2}
            />
          </div>
          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onClose(false)}
              disabled={loading}
            >
              Cancelar
            </button>
            <button type="submit" className={styles.btnSuccess} disabled={loading}>
              {loading ? 'Procesando...' : 'Pagar ahora'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ModalAjusteCCManual({ proveedor, empresas, onClose }) {
  const todayIso = () => new Date().toISOString().split('T')[0];
  const [form, setForm] = useState({
    empresa_id: proveedor.empresa_id ? String(proveedor.empresa_id) : '',
    fecha_movimiento: todayIso(),
    signo_ajuste: '1',
    monto: '',
    moneda: 'ARS',
    motivo: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.empresa_id) return setError('Empresa requerida.');
    const monto = parseFloat(form.monto);
    if (!Number.isFinite(monto) || monto <= 0) return setError('Monto > 0 requerido.');
    if (form.motivo.trim().length < 3) return setError('Motivo de al menos 3 caracteres.');

    setLoading(true);
    setError(null);
    try {
      await api.post(
        `/administracion/compras/cc-proveedor/${proveedor.id}/ajuste-manual`,
        {
          empresa_id: Number(form.empresa_id),
          fecha_movimiento: form.fecha_movimiento,
          signo_ajuste: Number(form.signo_ajuste),
          monto,
          moneda: form.moneda,
          motivo: form.motivo.trim(),
        }
      );
      onClose(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear el ajuste manual.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <Sliders size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Ajuste manual CC — {proveedor.nombre}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(false)}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </div>
        {error && <div className={styles.errorBanner}>{error}</div>}
        <p className={styles.modalHelp}>
          <FileText size={12} /> Append-only: agrega un movimiento de ajuste sin modificar
          los existentes. Uso crítico (compensaciones externas, correcciones
          históricas).
        </p>
        <form onSubmit={handleSubmit}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Empresa *</label>
            <select
              className={styles.select}
              value={form.empresa_id}
              onChange={(e) => setForm({ ...form, empresa_id: e.target.value })}
              required
            >
              <option value="">Seleccionar...</option>
              {empresas.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.nombre}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Tipo *</label>
              <select
                className={styles.select}
                value={form.signo_ajuste}
                onChange={(e) => setForm({ ...form, signo_ajuste: e.target.value })}
              >
                <option value="1">Debe (+) aumenta deuda</option>
                <option value="-1">Haber (-) reduce deuda</option>
              </select>
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Fecha *</label>
              <input
                type="date"
                className={styles.input}
                value={form.fecha_movimiento}
                onChange={(e) => setForm({ ...form, fecha_movimiento: e.target.value })}
                required
              />
            </div>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Moneda *</label>
              <select
                className={styles.select}
                value={form.moneda}
                onChange={(e) => setForm({ ...form, moneda: e.target.value })}
              >
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Monto *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                className={styles.input}
                value={form.monto}
                onChange={(e) => setForm({ ...form, monto: e.target.value })}
                required
              />
            </div>
          </div>
          <div className={styles.formGroup}>
            <label className={styles.formLabel}>Motivo *</label>
            <textarea
              className={styles.textarea}
              value={form.motivo}
              onChange={(e) => setForm({ ...form, motivo: e.target.value })}
              rows={3}
              placeholder="Describí el motivo con contexto suficiente para auditoría..."
              required
            />
          </div>
          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onClose(false)}
              disabled={loading}
            >
              Cancelar
            </button>
            <button type="submit" className={styles.btnDanger} disabled={loading}>
              {loading ? 'Guardando...' : 'Registrar ajuste'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
