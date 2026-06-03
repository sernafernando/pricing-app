import { useCallback, useEffect, useState } from 'react';
import {
  Layers,
  List,
  ChevronRight,
  Plus,
  Zap,
  Sliders,
  Eye,
  FileText,
  FileMinus,
  Receipt,
  X,
  Search as SearchIcon,
  Inbox,
  Coins,
  ArrowRight,
  Link2,
  Wallet,
  CreditCard,
  Undo2,
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
import ModalAplicarNC from './ModalAplicarNC';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import EstadoBadge from './_shared/EstadoBadge';
import EmptyState from './_shared/EmptyState';
import LoadingBlock from './_shared/LoadingBlock';
import MetricTile from './_shared/MetricTile';
import DataTable from './_shared/DataTable';
import SeccionDineroACuenta from './SeccionDineroACuenta';
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
 * Calcula running balance en ARS usando monto_ars del backend (F6).
 * Si monto_ars no está disponible (movimiento sin pedido vinculado),
 * cae en el monto nativo como antes.
 *
 * Convención libro mayor:
 *  - tipo='debe'                          → suma a Debe (incrementa deuda)
 *  - tipo='haber'                         → suma a Haber (paga deuda)
 *  - tipo='ajuste' con signo_ajuste=+1    → suma a Debe
 *  - tipo='ajuste' con signo_ajuste=-1    → suma a Haber
 *
 * Devuelve cada movimiento enriquecido con:
 *   { debeArs, haberArs, saldoArs }  — valores en ARS para display primario
 *   { debe, haber, saldoCorriente }  — valores nativos (para compat. existente)
 */
const enriquecerConDebeHaberYSaldo = (movimientos = []) => {
  const saldosPorMoneda = {};
  let saldoArsAcum = 0;
  return movimientos.map((m) => {
    // Native-currency amounts (fallback / secondary display).
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

    // F6 — ARS primary amounts from backend projection.
    // monto_ars is null for movements not linked to a pedido (rare).
    const montoArs = m.monto_ars != null ? Number(m.monto_ars) : null;
    let debeArs = null;
    let haberArs = null;
    if (montoArs != null) {
      if (m.tipo === 'debe') {
        debeArs = montoArs;
      } else if (m.tipo === 'haber') {
        haberArs = montoArs;
      } else if (m.tipo === 'ajuste') {
        if (m.signo_ajuste === 1) debeArs = montoArs;
        else if (m.signo_ajuste === -1) haberArs = montoArs;
      }
      saldoArsAcum += (debeArs || 0) - (haberArs || 0);
    }

    return {
      ...m,
      debe,
      haber,
      saldoCorriente,
      debeArs,
      haberArs,
      saldoArsAcum: montoArs != null ? saldoArsAcum : null,
    };
  });
};

export default function TabCCProveedores() {
  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  // El objeto `ccApi` se recrea en cada render; las funciones internas son estables.
  const {
    obtenerDetalle,
    obtenerPorPedido,
    listarImputaciones,
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

  const [empresas, setEmpresas] = useState([]);

  const [detalle, setDetalle] = useState(null);
  const [porPedido, setPorPedido] = useState([]);
  const [imputaciones, setImputaciones] = useState([]);
  const [tcEstimado, setTcEstimado] = useState(null);

  // Batch 6: NCs aprobadas del proveedor con saldo pendiente (FR-010).
  // Backend endpoint /administracion/compras/ncs-locales/disponibles.
  const [ncsDisponibles, setNcsDisponibles] = useState([]);

  // PR2 — breakdown del saldo a favor en componente real-money (DAC) vs documental (NC).
  const [saldoBreakdown, setSaldoBreakdown] = useState(null);

  // Batch 6: state para los modales que se abren desde el footer de
  // GrupoPedidoCard ("Aplicar NC" / "Imputar pago"). Ambos contextos llevan
  // pedidoId pre-cargado para el modal correspondiente.
  const [showAplicarNCDesdeCard, setShowAplicarNCDesdeCard] = useState(null); // { pedidoId, nc }
  const [showImputarPagoDesdeCard, setShowImputarPagoDesdeCard] = useState(null); // { pedidoId }

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

  // Desimputar imputación inline (motivo en modal de confirmación).
  const [confirmarDesimp, setConfirmarDesimp] = useState(null);
  const [motivoDesimp, setMotivoDesimp] = useState('');
  const [desimpLoading, setDesimpLoading] = useState(false);
  const [desimpError, setDesimpError] = useState(null);

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

  const fetchImputaciones = useCallback(async () => {
    if (!proveedorIdActivo) return;
    try {
      const data = await listarImputaciones({
        proveedor_id: proveedorIdActivo,
        page_size: 200,
      });
      setImputaciones(data?.items || []);
    } catch {
      setImputaciones([]);
    }
  }, [listarImputaciones, proveedorIdActivo]);

  // Batch 6 — T6.1: NCs aprobadas/aplicada_parcial con saldo pendiente del
  // proveedor activo. Si el endpoint falla, dejamos `[]` para no romper la
  // vista del CC (la sección del hero simplemente no se renderiza).
  const fetchNcsDisponibles = useCallback(async () => {
    if (!proveedorIdActivo) return;
    try {
      const { data } = await api.get(
        '/administracion/compras/ncs-locales/disponibles',
        { params: { proveedor_id: proveedorIdActivo, limit: 100 } }
      );
      setNcsDisponibles(Array.isArray(data) ? data : []);
    } catch (err) {
      // No bloqueante: el resto del CC sigue funcionando.
      console.error('fetchNcsDisponibles falló', err);
      setNcsDisponibles([]);
    }
  }, [proveedorIdActivo]);

  // PR2 — T2.12: fetch breakdown del saldo a favor (componente DAC vs NC).
  // No bloqueante: si falla, el CC sigue mostrando el saldo total.
  const fetchSaldoBreakdown = useCallback(async () => {
    if (!proveedorIdActivo) return;
    try {
      const { data } = await api.get(
        `/administracion/compras/proveedores/${proveedorIdActivo}/saldo-a-favor-breakdown`
      );
      setSaldoBreakdown(data || null);
    } catch {
      setSaldoBreakdown(null);
    }
  }, [proveedorIdActivo]);

  useEffect(() => {
    if (proveedorIdActivo) {
      fetchDetalle();
      fetchPorPedido();
      fetchImputaciones();
      fetchNcsDisponibles();
      fetchSaldoBreakdown();
    }
  }, [
    proveedorIdActivo,
    fetchDetalle,
    fetchPorPedido,
    fetchImputaciones,
    fetchNcsDisponibles,
    fetchSaldoBreakdown,
  ]);

  useEffect(() => {
    if (proveedorIdActivo) fetchDetalle();
  }, [filtroEmpresa, filtroHasta, fetchDetalle, proveedorIdActivo]);

  const saldos = detalle?.saldos || [];
  const saldoUsd = saldos.find((s) => s.moneda === 'USD')?.saldo || 0;
  const saldoArs = saldos.find((s) => s.moneda === 'ARS')?.saldo || 0;
  // F6 — saldo_ars: backend-computed ARS projection of ALL movements (§7.3).
  // Uses the effective TC of each pedido (manual > Caso-A weighted > original).
  // Falls back to the native ARS saldo when not available (old backend).
  const saldoArsProyectado = detalle?.saldo_ars != null ? Number(detalle.saldo_ars) : null;
  const consolidadoArs =
    tcEstimado && Number(saldoUsd) !== 0
      ? Number(saldoArs) + Number(saldoUsd) * tcEstimado
      : null;

  const movsArsCount = saldos.find((s) => s.moneda === 'ARS')?.movimientos_count || 0;
  const movsUsdCount = saldos.find((s) => s.moneda === 'USD')?.movimientos_count || 0;
  const initials = detalle ? getInitials(detalle.nombre_proveedor) : '';

  // Agrupar imputaciones por pedido_compra (destino) para mostrarlas inline.
  const imputacionesPorPedido = imputaciones.reduce((acc, imp) => {
    if (imp.destino_tipo === 'pedido_compra' && imp.destino_id) {
      const k = imp.destino_id;
      if (!acc[k]) acc[k] = [];
      acc[k].push(imp);
    }
    return acc;
  }, {});

  const handleDesimputar = async () => {
    if (!confirmarDesimp) return;
    const motivo = motivoDesimp.trim();
    if (motivo.length < 3) {
      setDesimpError('El motivo debe tener al menos 3 caracteres.');
      return;
    }
    setDesimpLoading(true);
    setDesimpError(null);
    try {
      await api.post(
        `/administracion/compras/imputaciones/${confirmarDesimp.id}/desimputar`,
        { motivo }
      );
      setConfirmarDesimp(null);
      setMotivoDesimp('');
      // Refrescar todo el CC: detalle, agrupado y lista de imputaciones.
      fetchDetalle();
      fetchPorPedido();
      fetchImputaciones();
    } catch (err) {
      setDesimpError(err.response?.data?.detail || 'Error al desimputar.');
    } finally {
      setDesimpLoading(false);
    }
  };

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
        <EmptyState
          icon={<SearchIcon size={36} strokeWidth={1.5} />}
          title="Buscá un proveedor"
          subtitle="Empezá tipeando el nombre o el CUIT en el buscador. La cuenta corriente aparece acá con todos los movimientos al instante."
          tone="hero"
        />
      ) : ccLoading && !detalle ? (
        <LoadingBlock text="Cargando cuenta corriente…" />
      ) : !detalle ? (
        <EmptyState
          icon={<Inbox size={36} strokeWidth={1.5} />}
          title="Sin datos"
          subtitle="No encontramos información para este proveedor con los filtros actuales."
          tone="hero"
        />
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
                value={
                  saldoArsProyectado !== null
                    ? formatMoneda(saldoArsProyectado, 'ARS')
                    : formatMoneda(saldoArs, 'ARS')
                }
                hint={
                  saldoArsProyectado !== null
                    ? `${movsArsCount + movsUsdCount} movimientos · TC efectivo por pedido`
                    : `${movsArsCount} movimientos`
                }
                tone={
                  (saldoArsProyectado ?? Number(saldoArs)) > 0
                    ? 'debe'
                    : (saldoArsProyectado ?? Number(saldoArs)) < 0
                      ? 'haber'
                      : 'neutral'
                }
              />
              {/* Tile USD eliminado — AC-1.3/AC-1.4: solo se muestra saldo ARS (saldo_ars proyectado). */}
              <MetricTile
                label="Consolidado ARS"
                value={consolidadoArs !== null ? formatMoneda(consolidadoArs, 'ARS') : '—'}
                hint={consolidadoArs !== null ? 'Estimado · TC del día' : 'TC no disponible'}
                tone="estimate"
              />
              {/* PR2 — T2.12: breakdown saldo a favor (DAC vs NC). Solo cuando hay saldo a favor. */}
              {saldoBreakdown &&
                Number(saldoBreakdown.componente_dinero_a_cuenta_ars) > 0 && (
                  <MetricTile
                    label="Dinero a cuenta"
                    value={formatMoneda(saldoBreakdown.componente_dinero_a_cuenta_ars, 'ARS')}
                    hint="Real-money disponible como medio de pago"
                    tone="haber"
                  />
                )}
              {saldoBreakdown &&
                Number(saldoBreakdown.componente_nc_ars) > 0 && (
                  <MetricTile
                    label="Crédito NC"
                    value={formatMoneda(saldoBreakdown.componente_nc_ars, 'ARS')}
                    hint="Crédito documental (NCs pendientes)"
                    tone="haber"
                  />
                )}
            </div>
          </section>

          {/* PR2 — T2.11: SeccionDineroACuenta — filas de dinero a cuenta disponibles */}
          {proveedorIdActivo && (
            <SeccionDineroACuenta proveedorId={proveedorIdActivo} />
          )}

          {/* ── Batch 6 — T6.2 — NCs disponibles del proveedor ──
              Render condicional: solo si el proveedor tiene NCs aprobadas con
              saldo pendiente > 0. Sin paginación (max 100 del backend). */}
          {ncsDisponibles.length > 0 && (
            <section className={styles.ncsDisponiblesHero}>
              <header className={styles.ncsDisponiblesHeader}>
                <FileMinus size={14} className={styles.ncsDisponiblesIcon} />
                <span className={styles.ncsDisponiblesTitle}>
                  NCs disponibles del proveedor
                </span>
                <span className={styles.ncsDisponiblesCount}>
                  {ncsDisponibles.length}
                </span>
              </header>
              <DataTable
                columns={[
                  { key: 'numero', label: 'Número', width: '140px' },
                  { key: 'fecha', label: 'Fecha', width: '110px' },
                  { key: 'importe', label: 'Importe', align: 'right', width: '160px' },
                  { key: 'saldo_pendiente', label: 'Saldo pendiente', align: 'right', width: '180px' },
                  { key: 'estado', label: 'Estado', width: '140px' },
                ]}
                rows={ncsDisponibles}
                renderCell={(row, col) => {
                  if (col.key === 'fecha') return formatDate(row.fecha);
                  if (col.key === 'importe') return formatMoneda(row.importe, row.moneda);
                  if (col.key === 'saldo_pendiente')
                    return formatMoneda(row.saldo_pendiente, row.moneda);
                  if (col.key === 'estado')
                    return <EstadoBadge variant="nc" estado={row.estado} />;
                  return row[col.key];
                }}
                minWidth="780px"
              />
            </section>
          )}

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

          {/* Vistas — comparten el mismo componente <LedgerTable /> */}
          {view === 'cronologico' ? (
            <LedgerTable
              movimientos={detalle.movimientos || []}
              onMovClick={(tipo, id) => setDetalleMov({ tipo, id })}
              emptyIcon={<Coins size={28} strokeWidth={1.5} />}
              emptyText="Sin movimientos en este periodo."
            />
          ) : (
            <div className={styles.grupoList}>
              {porPedido.length === 0 ? (
                <EmptyState
                  icon={<Layers size={28} strokeWidth={1.5} />}
                  title="Sin pedidos con movimientos en CC."
                  tone="default"
                />
              ) : (
                porPedido.map((g) => {
                  // Batch 6 — T6.4 (decisión pragmática): solo permitimos
                  // "Aplicar NC" desde el card si hay al menos una NC
                  // disponible del proveedor en la MISMA moneda que el pedido.
                  // ModalAplicarNC hoy requiere `nc` no-null (filtra pedidos
                  // por NC.moneda). Pre-cargamos la primera NC compatible y
                  // dejamos al user cerrar y elegir otra desde el hero si lo
                  // necesita. Si no hay NCs compatibles, el botón no aparece.
                  const ncCompatible = ncsDisponibles.find(
                    (n) => n.moneda === g.pedido_moneda
                  );
                  return (
                    <GrupoPedidoCard
                      key={g.pedido_compra_id}
                      grupo={g}
                      imputaciones={imputacionesPorPedido[g.pedido_compra_id] || []}
                      onMovClick={(tipo, id) => setDetalleMov({ tipo, id })}
                      onDesimputar={(imp) => {
                        setConfirmarDesimp(imp);
                        setMotivoDesimp('');
                        setDesimpError(null);
                      }}
                      onAplicarNC={
                        ncCompatible
                          ? (pid) =>
                              setShowAplicarNCDesdeCard({
                                pedidoId: pid,
                                nc: ncCompatible,
                              })
                          : null
                      }
                      onImputarPago={
                        canEjecutarPagos
                          ? (pid) =>
                              setShowImputarPagoDesdeCard({ pedidoId: pid })
                          : null
                      }
                    />
                  );
                })
              )}
            </div>
          )}
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

      {/* ── Batch 6 — T6.4 — Aplicar NC desde card de pedido ──
          Se monta cuando el user clickea "Aplicar NC" en GrupoPedidoCard.
          La NC viene pre-elegida (primera compatible por moneda); el modal
          recibe `pedidoDestinoId` y bloquea el selector de destino. */}
      {showAplicarNCDesdeCard && (
        <ModalAplicarNC
          nc={showAplicarNCDesdeCard.nc}
          pedidoDestinoId={showAplicarNCDesdeCard.pedidoId}
          onClose={(reload) => {
            setShowAplicarNCDesdeCard(null);
            if (reload) {
              fetchDetalle();
              fetchPorPedido();
              fetchImputaciones();
              fetchNcsDisponibles();
            }
          }}
        />
      )}

      {/* ── Batch 6 — T6.5 — Imputar pago desde card de pedido ──
          Abre ModalOrdenPagoNueva con pedido y proveedor pre-cargados. El
          modal soporta cross-moneda con TC (Batch 5). */}
      {showImputarPagoDesdeCard && proveedorCtx && (() => {
        const grupo = porPedido.find(
          (g) => g.pedido_compra_id === showImputarPagoDesdeCard.pedidoId
        );
        // El grupo del endpoint /por-pedido no trae empresa_id/proveedor_id,
        // pero ModalOrdenPagoNueva los requiere en `pedidoInicial`. Los
        // completamos desde el contexto del proveedor + filtro de empresa.
        const pedidoInicial = grupo
          ? {
              id: grupo.pedido_compra_id,
              numero: grupo.pedido_numero,
              empresa_id: filtroEmpresa
                ? Number(filtroEmpresa)
                : proveedorCtx.empresa_id,
              proveedor_id: proveedorCtx.id,
              moneda: grupo.pedido_moneda,
              monto: grupo.pedido_monto,
              saldo_pendiente: grupo.pedido_saldo_pendiente,
              tipo_cambio: grupo.pedido_tipo_cambio,
              estado: grupo.pedido_estado,
            }
          : null;
        if (!pedidoInicial) return null;
        return (
          <ModalOrdenPagoNueva
            empresas={empresas}
            proveedorInicial={proveedorCtx}
            pedidoInicial={pedidoInicial}
            pendientesDelProveedor={[]}
            onClose={(reload) => {
              setShowImputarPagoDesdeCard(null);
              if (reload) {
                fetchDetalle();
                fetchPorPedido();
                fetchImputaciones();
                fetchNcsDisponibles();
              }
            }}
          />
        );
      })()}

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

      {/* ── Confirmación desimputar (motivo obligatorio) ── */}
      {confirmarDesimp && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>
                <Undo2 size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                Desimputar imputación #{confirmarDesimp.id}
              </span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => {
                  setConfirmarDesimp(null);
                  setDesimpError(null);
                }}
                aria-label="Cerrar"
                type="button"
                disabled={desimpLoading}
              >
                <X size={18} />
              </button>
            </div>
            {desimpError && <div className={styles.errorBanner}>{desimpError}</div>}
            <p className={styles.modalHelp}>
              Crea un <strong>reversal</strong> que cancela el efecto de esta imputación
              (append-only — la imp original queda como auditoría). El saldo del pedido
              se restaura.
            </p>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Motivo *</label>
              <textarea
                className={styles.textarea}
                value={motivoDesimp}
                onChange={(e) => setMotivoDesimp(e.target.value)}
                placeholder="Describí por qué se desimputa (mínimo 3 chars)..."
                rows={3}
                disabled={desimpLoading}
              />
            </div>
            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => {
                  setConfirmarDesimp(null);
                  setDesimpError(null);
                }}
                disabled={desimpLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnDanger}
                onClick={handleDesimputar}
                disabled={desimpLoading}
              >
                {desimpLoading ? 'Desimputando…' : 'Desimputar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Internal helper components
// ══════════════════════════════════════════════════════════════════════════

const NAVEGABLE_TIPOS = ['pedido_compra', 'orden_pago', 'nota_credito_local'];

/**
 * Tabla libro mayor reutilizable. Misma estructura visual en vista
 * cronológica y dentro de cada card de pedido (resuelve el "choque visual"
 * entre vistas + el problema de columnas que se solapaban).
 */
function LedgerTable({ movimientos, onMovClick, emptyIcon, emptyText }) {
  const filas = enriquecerConDebeHaberYSaldo(movimientos);
  return (
    <div className={styles.tableWrapper}>
      <table className={styles.table}>
        <colgroup>
          <col className={styles.colFecha} />
          <col className={styles.colOrigen} />
          <col className={styles.colNum} />
          <col className={styles.colNum} />
          <col className={styles.colNum} />
          <col className={styles.colMon} />
          <col className={styles.colAccion} />
        </colgroup>
        <thead>
          <tr>
            <th className={styles.thLeft}>Fecha</th>
            <th className={styles.thLeft}>Origen / Descripción</th>
            <th className={styles.thRight}>Debe (ARS)</th>
            <th className={styles.thRight}>Haber (ARS)</th>
            <th className={styles.thRight}>Saldo (ARS)</th>
            <th className={styles.thCenter}>Mon.</th>
            <th aria-hidden="true" />
          </tr>
        </thead>
        <tbody>
          {filas.length === 0 ? (
            <tr>
              <td colSpan={7} className={styles.emptyRow}>
                <EmptyState
                  icon={emptyIcon}
                  title={emptyText || 'Sin movimientos.'}
                  tone="inline"
                />
              </td>
            </tr>
          ) : (
            filas.map((m) => {
              const navegable = m.origen_id && NAVEGABLE_TIPOS.includes(m.origen_tipo);
              const origenLabel =
                m.origen_descripcion ||
                `${m.origen_tipo}${m.origen_id ? ` #${m.origen_id}` : ''}`;
              return (
                <tr key={m.id} className={navegable ? styles.rowClickable : undefined}>
                  <td className={styles.tdSecondary}>{formatDate(m.fecha_movimiento)}</td>
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
                    {/* F6: primary display in ARS; native amount as muted secondary */}
                    {(m.debeArs != null ? m.debeArs > 0 : m.debe > 0) ? (
                      <>
                        {m.debeArs != null
                          ? formatMoneda(m.debeArs, 'ARS')
                          : formatMoneda(m.debe, m.moneda)}
                        {m.moneda !== 'ARS' && m.debeArs != null && m.debe > 0 && (
                          <div className={styles.tdEquivalenteArs}>
                            {formatMoneda(m.debe, m.moneda)}
                          </div>
                        )}
                      </>
                    ) : ''}
                  </td>
                  <td className={styles.tdRightHaber}>
                    {(m.haberArs != null ? m.haberArs > 0 : m.haber > 0) ? (
                      <>
                        {m.haberArs != null
                          ? formatMoneda(m.haberArs, 'ARS')
                          : formatMoneda(m.haber, m.moneda)}
                        {m.moneda !== 'ARS' && m.haberArs != null && m.haber > 0 && (
                          <div className={styles.tdEquivalenteArs}>
                            {formatMoneda(m.haber, m.moneda)}
                          </div>
                        )}
                      </>
                    ) : ''}
                  </td>
                  <td className={styles.tdRightSaldo}>
                    {m.saldoArsAcum != null
                      ? formatMoneda(m.saldoArsAcum, 'ARS')
                      : formatMoneda(m.saldoCorriente, m.moneda)}
                    {m.moneda !== 'ARS' && m.saldoArsAcum != null && (
                      <div className={styles.tdEquivalenteArs}>
                        {formatMoneda(m.saldoCorriente, m.moneda)}
                      </div>
                    )}
                  </td>
                  <td className={styles.tdMoneda}>{m.monto_ars != null ? 'ARS' : m.moneda}</td>
                  <td className={styles.tdAccion}>
                    {navegable && onMovClick && (
                      <button
                        type="button"
                        className={styles.iconBtn}
                        onClick={() => onMovClick(m.origen_tipo, m.origen_id)}
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
  );
}

/**
 * Card colapsable de un pedido en la vista "Por Pedido". Cerrado por default
 * — el summary muestra todo lo necesario para entender de un vistazo:
 *    P-XX-... [Estado] [Pagado/Parcial/Pendiente]    Total · Saldo
 * El body abre con la misma <LedgerTable /> que usa la vista cronológica
 * + una subsección con las imputaciones que apuntan a este pedido.
 */
function GrupoPedidoCard({
  grupo,
  imputaciones,
  onMovClick,
  onDesimputar,
  // Batch 6 — handlers nuevos. Cualquiera puede venir null si el feature
  // no aplica (ej. no hay NCs compatibles → onAplicarNC=null).
  onAplicarNC,
  onImputarPago,
}) {
  // Saldo del pedido en su moneda nativa (lo que falta pagar). Viene del
  // backend calculado como `pedido.monto - sum(imputaciones efectivas)`.
  // Si pedido es USD, este saldo es USD; el frontend lo convierte a ARS
  // multiplicando por tcPedido para visualización dinámica.
  const filas = enriquecerConDebeHaberYSaldo(grupo.movimientos);
  const saldoFinal =
    grupo.pedido_saldo_pendiente !== null && grupo.pedido_saldo_pendiente !== undefined
      ? Number(grupo.pedido_saldo_pendiente)
      : filas.length > 0
        ? filas[filas.length - 1].saldoCorriente
        : 0;
  const tienePendiente = Math.abs(saldoFinal) > 0.01;
  // Si pedido es USD y tiene TC, calculamos equivalente ARS para mostrar
  // junto al monto/saldo (la empresa paga en pesos).
  const tcPedido = grupo.pedido_tipo_cambio ? Number(grupo.pedido_tipo_cambio) : null;
  const mostrarEquivArs = grupo.pedido_moneda === 'USD' && tcPedido && tcPedido > 0;

  // Batch 6 — T6.7: TC ponderado por imputaciones cross-moneda. Solo se
  // renderiza si el backend lo expone (pedido USD con imps cross-moneda).
  // null => no se muestra nada (NO placeholder ni "TC pond.: -").
  const tcPonderadoVal =
    grupo.tc_ponderado !== null && grupo.tc_ponderado !== undefined
      ? Number(grupo.tc_ponderado)
      : null;

  // Mostramos footer solo si hay al menos una acción habilitada para evitar
  // un footer vacío en pedidos sin acciones disponibles.
  const hayAcciones = Boolean(onAplicarNC || onImputarPago);

  return (
    <details className={styles.grupoCard}>
      <summary className={styles.grupoSummary}>
        <span className={styles.grupoSummaryChevron} aria-hidden="true">
          <ChevronRight size={14} />
        </span>
        <div className={styles.grupoHeaderLeft}>
          <div className={styles.grupoHeaderLeftStack}>
            <div className={styles.grupoHeaderLeftRow}>
              <strong className={styles.grupoNumero}>{grupo.pedido_numero}</strong>
              <EstadoBadge variant="pedido" estado={grupo.pedido_estado} saldo={saldoFinal} />
            </div>
            {tcPonderadoVal !== null && (
              <span className={styles.tcPonderado}>
                TC pond.: {tcPonderadoVal.toFixed(2)}
              </span>
            )}
          </div>
        </div>
        <div className={styles.grupoHeaderRight}>
          <div className={styles.grupoHeaderTotals}>
            <div className={styles.grupoTotalRow}>
              <span className={styles.grupoTotalLabel}>Total</span>
              <div className={styles.grupoMontoBlock}>
                <span className={styles.grupoMonto}>
                  {mostrarEquivArs
                    ? formatMoneda(Number(grupo.pedido_monto) * tcPedido, 'ARS')
                    : formatMoneda(grupo.pedido_monto, grupo.pedido_moneda)}
                </span>
                {mostrarEquivArs && (
                  <span className={styles.grupoMontoSubvalue}>
                    {formatMoneda(grupo.pedido_monto, 'USD')} @ {tcPedido.toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                  </span>
                )}
              </div>
            </div>
            <div className={styles.grupoTotalRow}>
              <span className={styles.grupoTotalLabel}>Saldo</span>
              <span
                className={
                  tienePendiente ? styles.grupoSaldoPendiente : styles.grupoSaldoOk
                }
              >
                {mostrarEquivArs
                  ? formatMoneda(saldoFinal * tcPedido, 'ARS')
                  : formatMoneda(saldoFinal, grupo.pedido_moneda)}
              </span>
            </div>
          </div>
        </div>
      </summary>

      <div className={styles.grupoBody}>
        <LedgerTable
          movimientos={grupo.movimientos}
          onMovClick={onMovClick}
          emptyIcon={<Coins size={24} strokeWidth={1.5} />}
          emptyText="Sin movimientos en este pedido."
        />

        {/* Imputaciones que apuntan a este pedido (origen → destino) */}
        <div className={styles.impInline}>
          <div className={styles.impInlineHeader}>
            <Link2 size={12} />
            <span>Imputaciones</span>
            <span className={styles.impInlineCount}>
              {imputaciones.length}
            </span>
          </div>
          {imputaciones.length === 0 ? (
            <div className={styles.impInlineEmpty}>
              Este pedido todavía no tiene imputaciones.
            </div>
          ) : (
            <ul className={styles.impInlineList}>
              {imputaciones.map((imp) => (
                <li key={imp.id} className={styles.impInlineItem}>
                  <span
                    className={
                      imp.es_reversal ? styles.impInlineReversal : styles.impInlineNormal
                    }
                  >
                    {imp.es_reversal ? 'reversal' : 'imp'}
                  </span>
                  <span className={styles.impInlineOrigen}>
                    {imp.origen_descripcion || `${imp.origen_tipo} #${imp.origen_id}`}
                  </span>
                  <ArrowRight size={11} className={styles.impInlineArrow} />
                  <span className={styles.impInlineDestino}>
                    {imp.destino_descripcion ||
                      `${imp.destino_tipo} #${imp.destino_id}`}
                  </span>
                  <span className={styles.impInlineMonto}>
                    {formatMoneda(imp.monto_imputado, imp.moneda_imputada)}
                  </span>
                  {imp.varianza_tc_ars != null && (
                    <span
                      className={
                        Number(imp.varianza_tc_ars) >= 0
                          ? styles.varianzaPositiva
                          : styles.varianzaNegativa
                      }
                      title="Varianza de TC (diferencia ARS entre TC de registración y TC de pago)"
                    >
                      {Number(imp.varianza_tc_ars) >= 0 ? '+' : ''}
                      {formatMoneda(imp.varianza_tc_ars, 'ARS')}
                    </span>
                  )}
                  {onDesimputar && !imp.es_reversal && (
                    <button
                      type="button"
                      className={styles.iconBtn}
                      onClick={() => onDesimputar(imp)}
                      aria-label="Desimputar"
                      title="Desimputar (revertir esta imputación)"
                    >
                      <Undo2 size={12} />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ── Batch 6 — T6.3 — Footer de acciones por pedido ──
            "Aplicar NC" y "Imputar pago" abren modales pre-cargados con
            este pedido. Los handlers vienen del componente padre y pueden
            ser null si la acción no aplica (sin NCs / sin permiso). */}
        {hayAcciones && (
          <div className={styles.grupoActions}>
            {onAplicarNC && (
              <button
                type="button"
                className={styles.grupoActionBtn}
                onClick={() => onAplicarNC(grupo.pedido_compra_id)}
                title="Aplicar una NC del proveedor a este pedido"
              >
                <FileMinus size={13} /> Aplicar NC
              </button>
            )}
            {onImputarPago && (
              <button
                type="button"
                className={styles.grupoActionBtn}
                onClick={() => onImputarPago(grupo.pedido_compra_id)}
                title="Crear OP pre-cargada con este pedido como destino"
              >
                <CreditCard size={13} /> Imputar pago
              </button>
            )}
          </div>
        )}
      </div>
    </details>
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
