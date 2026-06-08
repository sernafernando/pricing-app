import { useCallback, useEffect, useMemo, useState } from 'react';
import { X, AlertTriangle, Check, Zap, Wallet, FileText, CreditCard } from 'lucide-react';
import api from '../../services/api';
import { useAuthStore } from '../../store/authStore';
import useComprasOP from '../../hooks/useComprasOP';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import PanelNCsProveedor from './_shared/PanelNCsProveedor';
import styles from './ModalOrdenPagoNueva.module.css';

/**
 * ModalOrdenPagoNueva — crea una OP con flujo anti-doble-contabilización.
 *
 * Piezas clave (design §7.3 + §7.4):
 *
 * 1. BANNER sessionStorage dismissable por día/usuario. Key:
 *    `compras_op_doble_contab_banner_dismissed_${userId}_${YYYYMMDD}`.
 *    TTL natural: sessionStorage se limpia al cerrar tab. Reset diario
 *    porque la key incluye la fecha.
 *
 * 2. MODO IMPUTACIÓN derivado automáticamente de los items (sin selector):
 *    - a_cuenta:  0 items (todo al saldo).
 *    - especifica: items presentes y suma === monto_total.
 *    - mixta:     items presentes y suma < monto_total (el resto va al saldo).
 *    - suma > monto_total: inválido — validar() bloquea el submit.
 *
 * 3. 409 POSIBLE_DUPLICADO_OP_ERP: si el backend responde 409, abrimos
 *    un modal HIJO con la lista de duplicados. "Confirmar, es distinto"
 *    reenvía el POST con `confirmar_duplicado: true` — el form queda
 *    abierto con todos los datos si el usuario cancela.
 *
 * REGLA AGENTS.md: NO cierra con click en overlay. Solo X o Cancelar.
 */

const todayYYYYMMDD = () => {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}${mm}${dd}`;
};

const bannerKeyFor = (userId) =>
  `compras_op_doble_contab_banner_dismissed_${userId}_${todayYYYYMMDD()}`;

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};


export default function ModalOrdenPagoNueva({
  empresas,
  onClose,
  pedidoInicial = null,
  pendientesDelProveedor = [],
  op = null,
  opItems = [],
  proveedorInicial = null,
}) {
  const user = useAuthStore((s) => s.user);
  const userId = user?.id || 'anon';
  const opApi = useComprasOP();

  // ── Modo edición ──
  // Si viene `op`, estamos editando una OP pendiente (sub-batch 1.1).
  // `opItems` debe ser la lista de items del último evento items_*
  // leída desde el detalle de la OP (items_editados si existe, sino
  // items_registrados). El componente NO va a la DB a buscarlos.
  const isEditMode = op !== null && op !== undefined;

  // ── Banner anti-doble-contab (solo en creación) ──
  const bannerKey = bannerKeyFor(userId);
  const [bannerDismissed, setBannerDismissed] = useState(
    isEditMode ? true : sessionStorage.getItem(bannerKey) === 'true'
  );

  const dismissBanner = () => {
    sessionStorage.setItem(bannerKey, 'true');
    setBannerDismissed(true);
  };

  // ── Form state ──
  // Prioridad: op (edit) > pedidoInicial (pre-carga) > defaults.
  const saldoInicial = pedidoInicial
    ? Number(pedidoInicial.saldo_pendiente ?? pedidoInicial.monto) || 0
    : 0;

  const [form, setForm] = useState(() => {
    if (isEditMode) {
      return {
        empresa_id: String(op.empresa_id ?? ''),
        proveedor_id: String(op.proveedor_id ?? ''),
        moneda: op.moneda || 'ARS',
        monto_total: String(op.monto_total ?? ''),
        tipo_cambio: op.tipo_cambio ? String(op.tipo_cambio) : '',
        observaciones: op.observaciones || '',
      };
    }
    return {
      empresa_id: pedidoInicial
        ? String(pedidoInicial.empresa_id)
        : proveedorInicial?.empresa_id
          ? String(proveedorInicial.empresa_id)
          : '',
      proveedor_id: pedidoInicial
        ? String(pedidoInicial.proveedor_id)
        : proveedorInicial?.id
          ? String(proveedorInicial.id)
          : '',
      moneda: pedidoInicial?.moneda || 'ARS',
      monto_total: pedidoInicial ? String(saldoInicial) : '',
      // Pre-cargar TC del pedido si viene (Feature B). Cuando el user cambia
      // de moneda, este TC se usa para convertir el monto.
      tipo_cambio: pedidoInicial?.tipo_cambio
        ? String(pedidoInicial.tipo_cambio)
        : '',
      observaciones: pedidoInicial
        ? `Pago imputado a pedido ${pedidoInicial.numero}`
        : '',
    };
  });

  const [items, setItems] = useState(() => {
    if (isEditMode) {
      return (opItems || []).map((it) => ({
        tipo: it.tipo || 'pedido_compra',
        id: it.id !== null && it.id !== undefined ? String(it.id) : '',
        monto: String(it.monto ?? ''),
        numero_factura: it.numero_factura || '',
      }));
    }
    return pedidoInicial
      ? [
          {
            tipo: 'pedido_compra',
            id: String(pedidoInicial.id),
            monto: String(saldoInicial),
            numero_factura: pedidoInicial.numero_factura || '',
          },
        ]
      : [];
  });

  // F1 — Actualizar TC del pedido (Caso A / Caso B).
  // Default: false (Caso B: el pago NO actualiza el TC efectivo del pedido).
  const [actualizarTcPedido, setActualizarTcPedido] = useState(false);

  // F3 — "Pagar ahora" toggle: cuando activo, envía a /crear-y-pagar.
  // Default: false → flujo original (solo crea la OP en estado pendiente).
  const [pagarAhora, setPagarAhora] = useState(false);
  const [cajas, setCajas] = useState([]);
  const [bancosEmpresa, setBancosEmpresa] = useState([]);
  const [loadingCajas, setLoadingCajas] = useState(false);
  const [loadingBancosEmpresa, setLoadingBancosEmpresa] = useState(false);
  const today = new Date().toISOString().split('T')[0];
  // fuenteKey: '' | 'caja:<id>' | 'banco:<id>'
  const [pagoForm, setPagoForm] = useState({ fuenteKey: '', fechaPagoReal: today, tipoCambioOverride: '' });

  const fetchCajas = useCallback(async () => {
    setLoadingCajas(true);
    try {
      const { data } = await api.get('/administracion-caja/cajas');
      setCajas(Array.isArray(data) ? data : []);
    } catch {
      setCajas([]);
    } finally {
      setLoadingCajas(false);
    }
  }, []);

  const fetchBancosEmpresaPago = useCallback(async (empresaId) => {
    if (!empresaId) return;
    setLoadingBancosEmpresa(true);
    try {
      const { data } = await api.get(
        `/administracion/bancos?solo_activos=true&empresa_id=${empresaId}`
      );
      // El endpoint /administracion/bancos devuelve { bancos: [...], total }.
      // (Antes se leía data.items, que no existe → los bancos nunca aparecían.)
      setBancosEmpresa(
        Array.isArray(data?.bancos)
          ? data.bancos
          : Array.isArray(data?.items)
            ? data.items
            : Array.isArray(data)
              ? data
              : []
      );
    } catch {
      setBancosEmpresa([]);
    } finally {
      setLoadingBancosEmpresa(false);
    }
  }, []);

  useEffect(() => {
    if (pagarAhora && cajas.length === 0) {
      fetchCajas();
    }
  }, [pagarAhora, cajas.length, fetchCajas]);

  useEffect(() => {
    if (pagarAhora) {
      fetchBancosEmpresaPago(form.empresa_id);
    }
  }, [pagarAhora, form.empresa_id, fetchBancosEmpresaPago]);

  // La fuente (caja/banco) DEBE coincidir con la moneda de la OP. Si cambia la
  // moneda de la OP y la fuente elegida ya no coincide, se limpia la selección.
  useEffect(() => {
    if (!pagoForm.fuenteKey) return;
    const [tipo, idStr] = pagoForm.fuenteKey.split(':');
    const fuente =
      tipo === 'caja'
        ? cajas.find((c) => String(c.id) === idStr)
        : bancosEmpresa.find((b) => String(b.id) === idStr);
    if (fuente && String(fuente.moneda) !== String(form.moneda)) {
      setPagoForm((prev) => ({ ...prev, fuenteKey: '' }));
    }
  }, [form.moneda, pagoForm.fuenteKey, cajas, bancosEmpresa]);

  const handlePagoFormChange = (campo, valor) => {
    setPagoForm((prev) => ({ ...prev, [campo]: valor }));
  };

  // F7 — NCs seleccionadas para aplicar al crear la OP.
  // Cada entrada: { nc_id, monto, pedido_id }.
  const [ncsAplicadas, setNcsAplicadas] = useState([]);

  // PR4 — Dinero a cuenta como medio de pago.
  // dacsDisponibles: lista de { id, monto, moneda, saldo_disponible, estado, origen_op_numero }
  // dacSeleccionado: id del DAC elegido (null = ninguno)
  // dacMonto: string con el monto a usar del DAC elegido
  const [dacsDisponibles, setDacsDisponibles] = useState([]);
  const [loadingDacs, setLoadingDacs] = useState(false);
  const [dacSeleccionado, setDacSeleccionado] = useState(null);
  const [dacMonto, setDacMonto] = useState('');
  const dacMontoNum = parseFloat(dacMonto) || 0;

  const fetchDacsDisponibles = useCallback(async (proveedorId, moneda) => {
    if (!proveedorId) {
      setDacsDisponibles([]);
      return;
    }
    setLoadingDacs(true);
    try {
      const { data } = await api.get(
        `/administracion/compras/proveedores/${proveedorId}/dinero-a-cuenta?estado=disponible&moneda=${moneda || 'ARS'}`
      );
      setDacsDisponibles(Array.isArray(data) ? data : []);
    } catch {
      setDacsDisponibles([]);
    } finally {
      setLoadingDacs(false);
    }
  }, []);

  useEffect(() => {
    if (form.proveedor_id) {
      fetchDacsDisponibles(form.proveedor_id, form.moneda);
      setDacSeleccionado(null);
      setDacMonto('');
    } else {
      setDacsDisponibles([]);
      setDacSeleccionado(null);
      setDacMonto('');
    }
  }, [form.proveedor_id, form.moneda, fetchDacsDisponibles]);

  // PR3 — Pago a cuenta explícito (excedente intencional).
  // El usuario ingresa el monto que quiere "apartar" como dinero a cuenta
  // del proveedor. Se incluye en el payload como item {tipo:'pago_a_cuenta'}.
  const [pagoACuenta, setPagoACuenta] = useState('');
  const pagoACuentaNum = parseFloat(pagoACuenta) || 0;
  // Refinement A — "touched" flag for pagoACuenta auto-fill.
  // Starts false on mount (fresh form). Becomes true on ANY user interaction
  // with the field (typing OR clearing). Once touched, auto-fill stops for
  // the lifetime of the modal so the user's opt-out is respected.
  // Auto-fill resumes only on a fresh modal open (useState resets to false).
  const [pagoACuentaTouched, setPagoACuentaTouched] = useState(false);

  // Bug B fix — "touched" flag for monto_total auto-sum.
  // When false (default), monto_total follows sumaItems (OP-currency doc sum) automatically.
  // Becomes true the moment the user manually edits the field (excedente intent),
  // disabling auto-sum for the lifetime of this modal instance.
  const [montoTotalTouched, setMontoTotalTouched] = useState(false);

  // PR5 — Warning shown when monto_total changes with 2+ items (FR-5.2).
  // Note: auto-clear when diferencia reaches 0 is handled in the render
  // (warning is gated on itemsSumWarning AND items.length > 1).
  const [itemsSumWarning, setItemsSumWarning] = useState(false);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  // Error inline específico del campo TC (Batch 5 — cross-moneda).
  const [tcError, setTcError] = useState(null);

  // ── 409 duplicado flow ──
  const [duplicadoInfo, setDuplicadoInfo] = useState(null);
  const [submittingConfirm, setSubmittingConfirm] = useState(false);

  // ── Confirm cambio de moneda con items pre-cargados ──
  // Cross-moneda OP↔pedido ahora SÍ está soportada cuando hay TC > 0
  // (Batch 3 backend + Batch 5 frontend). El confirm solo se dispara
  // como advertencia cuando NO hay TC válido: en ese caso el cambio
  // de moneda exigiría TC para imputar los items pre-cargados.
  const [confirmMoneda, setConfirmMoneda] = useState(null);

  // ── Modo imputación — derivado después de sumaItems (ver abajo) ──
  // La función recibe la suma en MONEDA OP (no el nativo de los items).
  // ADR-6: usar sumaItems (OP-currency) para no comparar äpples con naranjas
  // en operaciones cross-moneda (e.g. USD nativo << ARS total → mixta espuria).
  // 0 items         → a_cuenta
  // items, sumaOP === total → especifica
  // items, sumaOP < total  → mixta
  // (suma > total es inválido — validar() lo bloquea)
  // PR3: pago_a_cuenta se trata como item de cobertura para derivar el modo.
  const derivarModoImputacion = (sumaDocOP, total, hasItems, pacNum = 0) => {
    const hasPac = pacNum > 0;
    if (!hasItems && !hasPac) return 'a_cuenta';
    const sumaTotal = Math.round((sumaDocOP + pacNum) * 100) / 100;
    const totalR = Math.round((parseFloat(total) || 0) * 100) / 100;
    // Si hay items de documento y también pago_a_cuenta → mixta (hay mezcla de destinos)
    if (hasItems && hasPac) return 'mixta';
    return sumaTotal >= totalR ? 'especifica' : 'mixta';
  };

  // Lookup de pedido por id. Combina pendientesDelProveedor (lista del
  // dropdown) + pedidoInicial (pre-cargado vía prop, puede no estar en
  // la lista si la moneda del form ya difiere). Sin esto, cross-moneda
  // no se detecta cuando el user cambia la moneda del form.
  const pedidoDe = (id) => {
    if (!id) return null;
    const sid = String(id);
    const found = pendientesDelProveedor.find((p) => String(p.id) === sid);
    if (found) return found;
    if (pedidoInicial && String(pedidoInicial.id) === sid) return pedidoInicial;
    return null;
  };

  // Pedidos pendientes del proveedor actualmente seleccionado.
  // NO se filtran por moneda del form: cross-moneda con TC es válido,
  // así que el dropdown sigue mostrando todos los pedidos del proveedor.
  const pedidosDisponibles = pendientesDelProveedor.filter((p) => {
    if (form.proveedor_id && String(p.proveedor_id) !== String(form.proveedor_id)) {
      return false;
    }
    return true;
  });

  // Cross-moneda: hay al menos un item pedido_compra cuya moneda difiere
  // de la OP. Driver de UI (campo TC condicional, preview por item).
  const tieneCrossMoneda = items.some((it) => {
    if (it.tipo !== 'pedido_compra' || !it.id) return false;
    const pedido = pedidoDe(it.id);
    return !!pedido && pedido.moneda !== form.moneda;
  });

  // Moneda "del otro lado" cuando hay cross-moneda (para el label dinámico).
  // Si hay items en distintas monedas distintas a la OP, mostramos solo la
  // primera — improbable en práctica porque el flujo típico es un set
  // homogéneo de pedidos.
  const otraMonedaCross = (() => {
    for (const it of items) {
      if (it.tipo !== 'pedido_compra' || !it.id) continue;
      const pedido = pedidoDe(it.id);
      if (pedido && pedido.moneda !== form.moneda) return pedido.moneda;
    }
    return null;
  })();

  const tcNumLive = parseFloat(form.tipo_cambio);
  const tcValido = Number.isFinite(tcNumLive) && tcNumLive > 0;

  // ADR-6 — derive-at-edge: convierte el monto NATIVO del item a moneda OP en render.
  // items[].monto es siempre la moneda propia del pedido (inmutable).
  // Fórmulas: OP=ARS, pedido=USD → ARS = USD × TC; OP=USD, pedido=ARS → USD = ARS / TC.
  // Devuelve null si TC no es válido (NaN/0/vacío) para que la UI no muestre un número
  // incorrecto y el submit no mande basura.
  const montoEnMonedaOP = (item) => {
    const monto = parseFloat(item.monto);
    if (!Number.isFinite(monto) || monto <= 0) return null;
    if (item.tipo !== 'pedido_compra' || !item.id) {
      // Items sin pedido asociado (e.g. factura_erp sin datos de moneda) se asumen
      // en moneda OP — se devuelven tal cual.
      return monto;
    }
    const pedido = pedidoDe(item.id);
    if (!pedido) return monto; // pedido no encontrado — tratamos como same-moneda
    if (pedido.moneda === form.moneda) return monto; // same-moneda: nativo === OP
    // Cross-moneda: requiere TC válido para derivar
    if (!tcValido) return null;
    if (form.moneda === 'ARS' && pedido.moneda === 'USD') return monto * tcNumLive;
    if (form.moneda === 'USD' && pedido.moneda === 'ARS') return monto / tcNumLive;
    return monto; // misma moneda por otro camino
  };

  // itemsDerivados: items[] con montoDerivado calculado en render.
  // Recomputa automáticamente cada vez que cambia items, form.moneda o form.tipo_cambio.
  const itemsDerivados = useMemo(
    () => items.map((it) => ({ ...it, montoDerivado: montoEnMonedaOP(it) })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, form.moneda, form.tipo_cambio]
  );

  // IDs de pedidos ya agregados como items (para evitar duplicar al elegir del dropdown).
  const idsPedidosYaAgregados = new Set(
    items
      .filter((it) => it.tipo === 'pedido_compra' && it.id)
      .map((it) => String(it.id))
  );

  const handleChange = (campo, valor) => {
    // T1.14 — al cambiar proveedor, las NCs seleccionadas del proveedor
    // anterior quedan huérfanas: el backend las rechazaría (403/422).
    // Reseteamos siempre que cambia proveedor_id.
    if (campo === 'proveedor_id') {
      setNcsAplicadas([]);
      setDacSeleccionado(null);
      setDacMonto('');
      setItems([]);
      setItemsSumWarning(false);
    }

    // Bug B reconcile: monto_total is now auto-summed from documents.
    // Manual edits here signal excedente intent → mark touched to disable auto-sum.
    // We do NOT sync items[].monto from the typed total (items own their native amount).
    if (campo === 'monto_total') {
      setMontoTotalTouched(true);
    }

    setForm((f) => {
      const next = { ...f, [campo]: valor };
      if (campo === 'moneda' && valor !== f.moneda) {
        // Cross-moneda OP↔pedido ahora se soporta con TC > 0 (Batch 3 BE).
        // Solo advertimos al user si TC NO es válido: el cambio de moneda
        // dejaría items pedido_compra sin forma de imputarse.
        const tcNum = parseFloat(f.tipo_cambio);
        const tcOk = Number.isFinite(tcNum) && tcNum > 0;
        const tieneItemsPedido = items.some(
          (it) => it.tipo === 'pedido_compra' && it.id
        );
        if (tieneItemsPedido && !tcOk) {
          // Advertencia: el cambio queda en pausa hasta confirm.
          setConfirmMoneda({ from: f.moneda, to: valor });
          return f;
        }
        // OK: cross-moneda con TC válido OR sin items pedido_compra.
        // ADR-6: items[].monto es NATIVO — nunca lo reconvertimos al cambiar moneda.
        // El monto_total de la OP sí se convierte (es el total en moneda OP).
        const montoNum = parseFloat(f.monto_total);
        if (tcOk && Number.isFinite(montoNum) && montoNum > 0) {
          const nuevoMonto =
            f.moneda === 'USD' && valor === 'ARS'
              ? montoNum * tcNum
              : f.moneda === 'ARS' && valor === 'USD'
                ? montoNum / tcNum
                : montoNum;
          next.monto_total = nuevoMonto.toFixed(2);
        }
        // Cuando el user corrige la moneda, limpiamos cualquier error
        // previo del TC para no quedar con feedback obsoleto.
        setTcError(null);
        // T1.14 — NCs son moneda-específicas; al cambiar moneda se limpian.
        setNcsAplicadas([]);
      }
      // Cualquier edición del campo tipo_cambio limpia el error inline.
      // ADR-6: items[].monto es NATIVO — el TC no lo toca; itemsDerivados recomputa solo.
      // Bug B reconcile: monto_total now auto-sums from sumaItems (which depends on TC
      // via itemsDerivados), so no explicit TC→monto_total sync needed here.
      if (campo === 'tipo_cambio') {
        setTcError(null);
      }
      return next;
    });
  };

  // Aplica el cambio de moneda sin destruir items: el user verá los
  // items en cross-moneda y deberá cargar TC > 0 para poder hacer submit.
  // Es el flujo "entendí, voy a cargar TC". NO se limpian los items —
  // backend valida TC en submit y la UI muestra preview por item.
  const handleConfirmMoneda = () => {
    if (!confirmMoneda) return;
    setForm((f) => ({ ...f, moneda: confirmMoneda.to }));
    setConfirmMoneda(null);
  };

  // ── Checkbox-list handlers (nueva UX de selección de pedidos) ──

  // Per-item edit buffer for cross-moneda inputs.
  // Stores the raw OP-currency string the user is typing so the input
  // doesn't reformat on every keystroke. Keyed by pedidoId (string).
  // When NOT focused, the input derives its display value from native×TC.
  const [pedidoOpBuffers, setPedidoOpBuffers] = useState({});
  const [pedidoFocused, setPedidoFocused] = useState({});

  // Toggle check/uncheck de un pedido en la lista.
  const handlePedidoToggle = (pedido, checked) => {
    if (checked) {
      // ADR-6: items[].monto siempre en moneda NATIVA del pedido (INMUTABLE).
      // La conversión a moneda OP se hace en montoDerivado (useMemo) al render.
      const nativeMonto = Number(pedido.saldo_pendiente ?? pedido.monto ?? 0);
      const monto = nativeMonto > 0 ? nativeMonto.toFixed(2) : '';
      setItems((prev) => [
        ...prev,
        {
          tipo: 'pedido_compra',
          id: String(pedido.id),
          monto,
          numero_factura: pedido.numero_factura || '',
        },
      ]);
      // Clear any stale buffer when (re-)checking a pedido.
      setPedidoOpBuffers((prev) => {
        const next = { ...prev };
        delete next[String(pedido.id)];
        return next;
      });
    } else {
      setItems((prev) => prev.filter((it) => String(it.id) !== String(pedido.id)));
      setPedidoOpBuffers((prev) => {
        const next = { ...prev };
        delete next[String(pedido.id)];
        return next;
      });
      setPedidoFocused((prev) => {
        const next = { ...prev };
        delete next[String(pedido.id)];
        return next;
      });
    }
    setItemsSumWarning(false);
  };

  // Editar el monto de un pedido ya chequeado.
  // Para items same-moneda: valor es el monto nativo directo (comportamiento anterior).
  // Para items cross-moneda: valor es en moneda OP; back-computamos el nativo antes
  // de guardar en items[].monto (ADR-6: source of truth stays native).
  const handlePedidoMonto = (pedidoId, valor, isCross = false) => {
    if (isCross) {
      // valor is the OP-currency string typed by the user.
      // Update the display buffer immediately (no flicker).
      setPedidoOpBuffers((prev) => ({ ...prev, [String(pedidoId)]: valor }));
      // Back-compute native from OP value.
      const opNum = parseFloat(valor);
      if (Number.isFinite(opNum) && opNum > 0 && tcValido) {
        const item = items.find((it) => String(it.id) === String(pedidoId));
        const ped = item?.tipo === 'pedido_compra' && item.id ? pedidoDe(item.id) : null;
        if (ped) {
          let nativo;
          if (form.moneda === 'ARS' && ped.moneda === 'USD') {
            nativo = opNum / tcNumLive; // peso / TC = USD
          } else if (form.moneda === 'USD' && ped.moneda === 'ARS') {
            nativo = opNum * tcNumLive; // USD × TC = ARS
          } else {
            nativo = opNum;
          }
          const nativoStr = nativo.toFixed(2);
          setItems((prev) => {
            const next = prev.map((it) =>
              String(it.id) === String(pedidoId) ? { ...it, monto: nativoStr } : it
            );
            if (next.length > 1) {
              // For cross-moneda items use derived OP value for warning check.
              const sumaActual = next.reduce((acc, it) => {
                const itPed = it.tipo === 'pedido_compra' && it.id ? pedidoDe(it.id) : null;
                const itNativo = parseFloat(it.monto) || 0;
                if (!itPed || itPed.moneda === form.moneda) return acc + itNativo;
                if (!tcValido) return acc;
                return acc + (form.moneda === 'ARS' ? itNativo * tcNumLive : itNativo / tcNumLive);
              }, 0);
              const totalNum = parseFloat(form.monto_total) || 0;
              if (Math.abs(sumaActual - totalNum) <= 0.005) setItemsSumWarning(false);
            }
            return next;
          });
        }
      } else if (valor === '' || valor === '0') {
        // Clear: store empty native.
        setItems((prev) =>
          prev.map((it) =>
            String(it.id) === String(pedidoId) ? { ...it, monto: '' } : it
          )
        );
      }
      return;
    }

    // Same-moneda path (unchanged).
    setItems((prev) => {
      const next = prev.map((it) =>
        String(it.id) === String(pedidoId) ? { ...it, monto: valor } : it
      );
      // Auto-dismiss warning when sum matches total.
      if (next.length > 1) {
        const sumaActual = next.reduce((acc, it) => acc + (parseFloat(it.monto) || 0), 0);
        const totalNum = parseFloat(form.monto_total) || 0;
        if (Math.abs(sumaActual - totalNum) <= 0.005) {
          setItemsSumWarning(false);
        }
      }
      return next;
    });
  };

  // ── Validación ──
  // sumaItems suma montoDerivado (en moneda OP) de todos los items.
  // Items sin TC válido (montoDerivado === null) contribuyen 0 — el validar()
  // los bloquea antes del submit si hay cross-moneda sin TC.
  const sumaItems = itemsDerivados.reduce((acc, it) => acc + (it.montoDerivado ?? 0), 0);
  const montoTotalNum = parseFloat(form.monto_total) || 0;

  // Bug A fix — modoImputacion computed from OP-currency doc sum (sumaItems),
  // NOT from native item.monto. This prevents cross-moneda "mixta" misfires
  // where native USD << ARS total but OP-currency sum == total → 'especifica'.
  const modoImputacion = derivarModoImputacion(sumaItems, form.monto_total, items.length > 0, pagoACuentaNum);

  // PR3/PR4 — NC/DAC now SUBTRACT from the total (new money model).
  //
  // sumaNCsOP: NCs converted to OP currency using each NC's own tipo_cambio
  // (with optional per-NC override supplied by the panel).
  //   same-moneda:        nc.monto
  //   OP=ARS, NC=USD:     nc.monto × tc
  //   OP=USD, NC=ARS:     nc.monto ÷ tc
  const sumaNCsOP = ncsAplicadas.reduce((acc, nc) => {
    const montoNC = parseFloat(nc.monto) || 0;
    if (nc.moneda === undefined || nc.moneda === form.moneda) {
      // Same-moneda or no moneda info — use monto directly.
      return acc + montoNC;
    }
    // Cross-moneda: use override if set, else nc.tipo_cambio.
    const tc = parseFloat(nc.tipo_cambio_override) > 0
      ? parseFloat(nc.tipo_cambio_override)
      : parseFloat(nc.tipo_cambio);
    if (!Number.isFinite(tc) || tc <= 0) return acc + montoNC; // fallback: treat as same-moneda
    // Convertir y redondear POR-NC a 2 decimales, igual que el backend
    // (fx_service.q_ars/q_usd redondea cada NC antes de sumar). Si el front sumara
    // a precisión float y redondeara el agregado, podría diferir 1 centavo del
    // balance del backend → 422 espurio al pagar.
    let convertido = montoNC;
    if (form.moneda === 'ARS' && nc.moneda === 'USD') convertido = montoNC * tc;
    else if (form.moneda === 'USD' && nc.moneda === 'ARS') convertido = montoNC / tc;
    return acc + Math.round(convertido * 100) / 100;
  }, 0);

  // sumaDAC: same-moneda only (DAC has no tipo_cambio), subtract directly.
  const sumaDAC = dacMontoNum;

  // net: the cash amount the user needs to pay (items minus discounts).
  // pago_a_cuenta is additive — it represents an intentional surplus.
  const net = Math.round((sumaItems - sumaNCsOP - sumaDAC) * 100) / 100;

  // diferencia: how far monto_total is from net (excluding excedente).
  // == 0 → balanced; > 0 → falta cubrir; < 0 → extra (unusual, won't happen in normal flow).
  const diferencia = Math.round((montoTotalNum - net - pagoACuentaNum) * 100) / 100;


  // Auto-sum monto_total = net (sumaItems − sumaNCsOP − sumaDAC).
  // NCs and DAC now participate: applying an NC lowers the auto-summed total.
  // Skips: edit mode, user has manually touched the field, or no items (a_cuenta).
  // No loop: net depends on sumaItems/sumaNCsOP/sumaDAC (not on monto_total),
  // and monto_total doesn't feed back into net. Setting monto_total here is safe.
  useEffect(() => {
    if (isEditMode || montoTotalTouched || items.length === 0) return;
    const target = Math.max(0, net).toFixed(2);
    if (form.monto_total !== target) {
      setForm((f) => ({ ...f, monto_total: target }));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [net, isEditMode, montoTotalTouched, items.length]);

  // Refinement A — auto-fill pagoACuenta = max(0, montoTotalNum − net) when:
  //   - not in edit mode
  //   - the user has NOT touched the field yet (pagoACuentaTouched === false)
  // The excedente is the intentional surplus the user introduces by raising monto_total
  // above net (= sumaItems − sumaNCsOP − sumaDAC).
  // When monto_total === net (default), excedente = 0 → field stays empty.
  //
  // No loop: setPagoACuenta does NOT touch pagoACuentaTouched. Effect fires on
  // montoTotalNum or net change; pagoACuentaTouched gates early return.
  useEffect(() => {
    if (isEditMode || pagoACuentaTouched) return;
    const surplus = Math.max(0, Math.round((montoTotalNum - net) * 100) / 100);
    const target = surplus > 0 ? String(surplus) : '';
    setPagoACuenta(target);
  }, [montoTotalNum, net, isEditMode, pagoACuentaTouched]);


  const validar = () => {
    if (!form.empresa_id) return 'Empresa requerida.';
    if (!form.proveedor_id) return 'Proveedor requerido.';
    if (!Number.isFinite(montoTotalNum) || montoTotalNum <= 0)
      return 'El monto total debe ser mayor a 0.';
    if (!['ARS', 'USD'].includes(form.moneda)) return 'Moneda inválida.';

    if (items.length > 0) {
      for (const [idx, it] of items.entries()) {
        if (!it.tipo || !['pedido_compra', 'factura_erp'].includes(it.tipo))
          return `Item #${idx + 1}: tipo inválido.`;
        if (!it.id) return `Item #${idx + 1}: id requerido.`;
        const m = parseFloat(it.monto);
        if (!Number.isFinite(m) || m <= 0) return `Item #${idx + 1}: monto > 0 requerido.`;
      }
    }
    // PR3: pago_a_cuenta no puede ser negativo.
    if (pagoACuentaNum < 0) return 'El pago a cuenta no puede ser negativo.';
    // PR3: al confirmar (crear y pagar), la diferencia debe ser 0.
    // Al solo crear (draft), se permite diferencia != 0.
    if (pagarAhora && diferencia !== 0) {
      return `Diferencia de ${formatCurrency(Math.abs(diferencia), form.moneda)} — la cobertura debe ser igual al total para confirmar el pago.`;
    }
    return null;
  };

  // TC requerido cuando OP es USD (UX histórica) o cuando hay cross-moneda
  // (Batch 5 — backend valida y rechaza si llega null/<=0).
  const requiereTc = form.moneda === 'USD' || tieneCrossMoneda;
  const tcEnviable = requiereTc && tcValido ? tcNumLive : null;

  const buildPayload = (confirmarDuplicado = false) => {
    const base = {
      empresa_id: Number(form.empresa_id),
      proveedor_id: Number(form.proveedor_id),
      moneda: form.moneda,
      monto_total: montoTotalNum,
      tipo_cambio: tcEnviable,
      modo_imputacion: modoImputacion,
      observaciones: form.observaciones || null,
      items: [
        // ADR-6: el backend espera monto en moneda OP. Derivamos en el momento
        // del submit desde el monto nativo + TC actual (nunca desde el nativo mutado).
        ...itemsDerivados.map((it) => ({
          tipo: it.tipo,
          id: it.id ? Number(it.id) : null,
          monto: it.montoDerivado ?? parseFloat(it.monto),
          numero_factura: it.numero_factura || null,
        })),
        // PR3: pago_a_cuenta como item explícito cuando el usuario lo indica
        ...(pagoACuentaNum > 0
          ? [{ tipo: 'pago_a_cuenta', id: null, monto: pagoACuentaNum }]
          : []),
        // PR4: dinero_a_cuenta como medio de pago cuando el usuario lo indica.
        // destino_tipo/destino_id: el primer pedido/factura del OP (el backend
        // infiere si no se envía, pero lo enviamos explícito para mayor claridad).
        ...(dacSeleccionado && dacMontoNum > 0
          ? (() => {
              const primerDestino = items.find(
                (it) => it.tipo === 'pedido_compra' || it.tipo === 'factura_erp'
              );
              return [{
                tipo: 'dinero_a_cuenta',
                id: dacSeleccionado,
                monto: dacMontoNum,
                destino_tipo: primerDestino ? primerDestino.tipo : 'pedido_compra',
                destino_id: primerDestino && primerDestino.id ? Number(primerDestino.id) : null,
              }];
            })()
          : []),
      ],
      confirmar_duplicado: confirmarDuplicado,
      actualizar_tc_pedido: actualizarTcPedido,
      // F7 — NCs a aplicar en la misma transacción (solo en creación, no edición).
      // tipo_cambio_override is forwarded when the user overrode the NC's TC in the panel.
      ncs_aplicadas: isEditMode
        ? []
        : ncsAplicadas.map((nc) => {
            const entry = { nc_id: nc.nc_id, monto: nc.monto, pedido_id: nc.pedido_id };
            if (nc.tipo_cambio_override != null) {
              entry.tipo_cambio_override = nc.tipo_cambio_override;
            }
            return entry;
          }),
    };
    if (pagarAhora) {
      const [fuenteTipo, fuenteIdStr] = (pagoForm.fuenteKey || '').split(':');
      const fuenteId = Number(fuenteIdStr);
      if (fuenteTipo === 'banco') {
        base.banco_id = fuenteId;
      } else {
        base.caja_id = fuenteId;
      }
      base.fecha_pago_real = pagoForm.fechaPagoReal;
      const tcOv = parseFloat(pagoForm.tipoCambioOverride);
      if (Number.isFinite(tcOv) && tcOv > 0) {
        base.tipo_cambio_override = tcOv;
      }
    }
    return base;
  };

  const buildEditPayload = () => ({
    monto_total: montoTotalNum,
    moneda: form.moneda,
    tipo_cambio: tcEnviable,
    modo_imputacion: modoImputacion,
    observaciones: form.observaciones || null,
    items: itemsDerivados.map((it) => ({
      tipo: it.tipo,
      id: it.id ? Number(it.id) : null,
      monto: it.montoDerivado ?? parseFloat(it.monto),
      numero_factura: it.numero_factura || null,
    })),
  });

  const handleSubmit = async (e) => {
    e.preventDefault();
    // Validación específica del TC (Batch 5): error inline en el campo,
    // no banner global. Si falta TC y se requiere, abortamos antes de
    // mandar al backend (que también valida con 400).
    if (requiereTc && !tcValido) {
      setTcError(
        tieneCrossMoneda
          ? 'TC requerido (> 0) para imputar items en otra moneda.'
          : 'TC requerido (> 0) cuando la OP es USD.'
      );
      return;
    }
    setTcError(null);
    const v = validar();
    if (v) {
      setError(v);
      return;
    }
    // F3: validate payment fields when "Pagar ahora" is ON.
    if (pagarAhora && !pagoForm.fuenteKey) {
      setError('Seleccioná una fuente de fondos (caja o banco) para ejecutar el pago.');
      return;
    }
    if (pagarAhora && !pagoForm.fechaPagoReal) {
      setError('La fecha de pago es requerida.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (isEditMode) {
        await opApi.editar(op.id, buildEditPayload());
        onClose(true);
        return;
      }
      if (pagarAhora) {
        // AC3.5: "Pagar ahora" ON → submit to /crear-y-pagar.
        await opApi.crearYPagar(buildPayload(false));
      } else {
        // AC3.4: "Pagar ahora" OFF → original flow (crear OP pendiente).
        await opApi.crear(buildPayload(false));
      }
      onClose(true);
    } catch (err) {
      const res = err.response;
      if (res?.status === 409) {
        // El backend payload puede venir como dict directo O como
        // { error: { code, message } } debido al handler del proyecto.
        const raw = res.data?.detail ?? res.data ?? {};
        const codigo =
          raw.codigo ||
          raw.code ||
          res.data?.error?.code ||
          (typeof raw === 'string' && raw.includes('POSIBLE_DUPLICADO_OP_ERP')
            ? 'POSIBLE_DUPLICADO_OP_ERP'
            : null);
        if (codigo === 'POSIBLE_DUPLICADO_OP_ERP') {
          setDuplicadoInfo({
            mensaje:
              raw.mensaje ||
              'Detectamos en el ERP una OP reciente para este proveedor. Verificá antes de continuar.',
            duplicados: Array.isArray(raw.duplicados_detectados)
              ? raw.duplicados_detectados
              : Array.isArray(raw.duplicados)
              ? raw.duplicados
              : [],
          });
        } else {
          setError(res.data?.detail || 'Conflicto al crear la OP.');
        }
      } else {
        // Destapar el mensaje real del backend, que puede venir en varias formas:
        // detail string, detail.{mensaje}, detail[] (422 validación), o {error:{message}}.
        const d = res?.data;
        const msg =
          (typeof d?.detail === 'string' && d.detail) ||
          d?.detail?.mensaje ||
          (Array.isArray(d?.detail) &&
            d.detail.map((e) => e?.msg || e?.mensaje || JSON.stringify(e)).join('; ')) ||
          d?.error?.message ||
          d?.mensaje ||
          d?.message ||
          err.message ||
          'Error al crear la OP.';
        setError(msg);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmarDuplicado = async () => {
    setSubmittingConfirm(true);
    setError(null);
    try {
      if (pagarAhora) {
        await opApi.crearYPagar(buildPayload(true));
      } else {
        await opApi.crear(buildPayload(true));
      }
      onClose(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear la OP con confirmación.');
      setDuplicadoInfo(null);
    } finally {
      setSubmittingConfirm(false);
    }
  };

  // ── Derived display helpers ──
  const proveedorNombre = pedidoInicial?.proveedor_nombre ?? proveedorInicial?.nombre ?? null;
  const empresaNombre = pedidoInicial?.empresa_nombre ?? empresas.find((e) => String(e.id) === String(form.empresa_id))?.nombre ?? null;
  const isPreFilled = !!(proveedorNombre && empresaNombre);

  const diferenciaStatus = diferencia === 0
    ? 'ok'
    : diferencia > 0
      ? 'falta'
      : 'exceso';

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>

        {/* ── Header ── */}
        <header className={styles.modalHeader}>
          <div className={styles.headerTitles}>
            <h1 className={styles.modalTitle}>
              {isEditMode ? `Editar OP ${op.numero}` : 'Nueva Orden de Pago'}
            </h1>
            {isPreFilled && (
              <p className={styles.headerSubtitle}>
                Proveedor: <strong>{proveedorNombre}</strong>
                {empresaNombre && (
                  <> · Empresa: <strong>{empresaNombre}</strong></>
                )}
              </p>
            )}
          </div>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(false)}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </header>

        {/* ── Banner anti-doble-contabilización ── */}
        {!bannerDismissed && (
          <div className={styles.banner} role="alert">
            <AlertTriangle size={20} className={styles.bannerIcon} />
            <div className={styles.bannerBody}>
              <strong>Atención:</strong> Si este pago ya se registró directamente en el ERP,
              NO lo cargues acá. Se contabilizaría dos veces.
            </div>
            <button
              type="button"
              className={styles.bannerDismiss}
              onClick={dismissBanner}
            >
              Entendido
            </button>
          </div>
        )}

        {error && <div className={styles.errorBanner}>{error}</div>}

        {/* ── Two-column body ── */}
        <form onSubmit={handleSubmit}>
          <div className={styles.bodyGrid}>

            {/* ══════════════════ LEFT COLUMN ══════════════════ */}
            <main className={styles.leftCol}>

              {/* ── Selectors (empresa/proveedor) when not pre-filled ── */}
              {!isPreFilled && (
                <section className={styles.formSection}>
                  <div className={styles.formRow2}>
                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Empresa *</label>
                      <select
                        className={styles.select}
                        value={form.empresa_id}
                        onChange={(e) => handleChange('empresa_id', e.target.value)}
                        required
                        disabled={!!pedidoInicial || isEditMode}
                        title={
                          pedidoInicial
                            ? 'Empresa heredada del pedido (no editable para evitar inconsistencias)'
                            : undefined
                        }
                      >
                        <option value="">Seleccionar...</option>
                        {empresas.map((emp) => (
                          <option key={emp.id} value={emp.id}>
                            {emp.nombre}
                          </option>
                        ))}
                      </select>
                      {pedidoInicial && (
                        <div className={styles.fieldHint}>
                          Heredada del pedido {pedidoInicial.numero}
                        </div>
                      )}
                    </div>

                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Proveedor *</label>
                      <ProveedorComprasAutocomplete
                        value={form.proveedor_id ? Number(form.proveedor_id) : null}
                        onChange={(id) => handleChange('proveedor_id', id ? String(id) : '')}
                        disabled={saving}
                      />
                    </div>
                  </div>
                </section>
              )}

              {/* ── Moneda / Monto total / TC ── */}
              <section className={styles.formSection}>
                <div className={styles.formRow2}>
                  <div className={styles.formGroup}>
                    <label className={styles.formLabel}>Moneda *</label>
                    <select
                      className={styles.select}
                      value={form.moneda}
                      onChange={(e) => handleChange('moneda', e.target.value)}
                    >
                      <option value="ARS">ARS</option>
                      <option value="USD">USD</option>
                    </select>
                  </div>

                  <div className={styles.formGroup}>
                    <label className={styles.formLabel}>Monto total *</label>
                    <input
                      type="number"
                      step="0.01"
                      min="0.01"
                      className={styles.inputMono}
                      value={form.monto_total}
                      onChange={(e) => handleChange('monto_total', e.target.value)}
                      placeholder="0.00"
                      required
                    />
                  </div>
                </div>

                {(form.moneda === 'USD' || tieneCrossMoneda) && (
                  <div className={styles.formGroup}>
                    <label className={styles.formLabel}>
                      {tieneCrossMoneda && otraMonedaCross
                        ? `TC ${form.moneda} ↔ ${otraMonedaCross} *`
                        : 'Tipo de cambio (ARS por 1 USD) *'}
                    </label>
                    <input
                      type="number"
                      step="0.0001"
                      min="0"
                      className={`${styles.inputMono}${tcError ? ` ${styles.inputError}` : ''}`}
                      value={form.tipo_cambio}
                      onChange={(e) => handleChange('tipo_cambio', e.target.value)}
                      placeholder="Ej: 1500"
                      aria-invalid={tcError ? 'true' : 'false'}
                      aria-describedby={tcError ? 'tc-error' : undefined}
                    />
                    {tcError ? (
                      <div id="tc-error" className={styles.errorInline} role="alert">
                        {tcError}
                      </div>
                    ) : (
                      <div className={styles.fieldHint}>
                        {tieneCrossMoneda
                          ? `Necesario para imputar items en ${otraMonedaCross}. Backend rechaza sin TC > 0.`
                          : 'Si cambiás de moneda con TC válido, los montos se convierten automáticamente.'}
                      </div>
                    )}
                  </div>
                )}

                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Observaciones</label>
                  <textarea
                    className={styles.textarea}
                    value={form.observaciones}
                    onChange={(e) => handleChange('observaciones', e.target.value)}
                    placeholder="Notas internas..."
                    rows={2}
                  />
                </div>

                {/* F1 — Actualizar TC del pedido al ejecutar */}
                {!isEditMode && (
                  <div className={styles.formGroupCheckbox}>
                    <label className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        className={styles.checkbox}
                        checked={actualizarTcPedido}
                        onChange={(e) => setActualizarTcPedido(e.target.checked)}
                      />
                      <span>Actualizar TC del pedido al ejecutar (Caso A)</span>
                    </label>
                    <div className={styles.fieldHint}>
                      Al ejecutar el pago, el TC efectivo del pedido se recalculará usando el
                      promedio ponderado de todos los pagos con esta opción activa.
                      Si no lo activás, el TC original del pedido se mantiene (Caso B).
                    </div>
                  </div>
                )}
              </section>

              {/* ── DOCUMENTOS A PAGAR ── */}
              <section className={styles.formSection}>
                <h2 className={styles.sectionHeading}>
                  <FileText size={13} className={styles.sectionHeadingIcon} />
                  Documentos a pagar
                </h2>

                {pedidosDisponibles.length === 0 ? (
                  <div className={styles.emptyItems}>
                    Este proveedor no tiene pedidos pendientes.
                  </div>
                ) : (
                  <div className={styles.pedidosCheckboxList}>
                    {pedidosDisponibles.map((pedido) => {
                      const pedidoId = String(pedido.id);
                      const isChecked = idsPedidosYaAgregados.has(pedidoId);
                      const itemActual = items.find((it) => String(it.id) === pedidoId);
                      const montoActual = itemActual ? itemActual.monto : ''; // nativo del pedido

                      const pedidoItemData = pedidoDe(pedidoId);
                      const isCross =
                        !!pedidoItemData && pedidoItemData.moneda !== form.moneda;

                      // For cross-moneda: derive the OP-currency display value.
                      // While focused, show the raw buffer; otherwise show formatted derived.
                      const itemDerivado = itemsDerivados.find((it) => String(it.id) === pedidoId);
                      const opDerived = itemDerivado?.montoDerivado; // null if TC invalid

                      const isFocused = !!pedidoFocused[pedidoId];
                      let inputValue;
                      let inputSymbol;
                      if (isCross) {
                        inputSymbol = form.moneda === 'USD' ? 'US$' : '$';
                        if (isFocused) {
                          // Show raw buffer while typing (no reformatting mid-keystroke).
                          inputValue = pedidoOpBuffers[pedidoId] ?? (opDerived != null ? opDerived.toFixed(2) : '');
                        } else {
                          // Not focused: show formatted derived value (updates on TC change).
                          inputValue = opDerived != null ? opDerived.toFixed(2) : (pedidoOpBuffers[pedidoId] ?? '');
                        }
                      } else {
                        inputSymbol = null;
                        inputValue = montoActual;
                      }

                      // Small native reference line shown below the OP-currency input.
                      let nativeRefLine = null;
                      if (isCross && isChecked) {
                        const nativoNum = parseFloat(montoActual);
                        if (Number.isFinite(nativoNum) && nativoNum > 0) {
                          nativeRefLine = `Cancelás ${formatCurrency(nativoNum, pedidoItemData.moneda)}`;
                        } else if (!tcValido) {
                          nativeRefLine = 'Ingresá TC para ver equivalente nativo';
                        }
                      }

                      return (
                        <div
                          key={pedidoId}
                          className={`${styles.pedidoRow} ${isChecked ? styles.pedidoRowChecked : ''}`}
                        >
                          <div className={styles.pedidoRowHeader}>
                            <div className={styles.pedidoRowLeft}>
                              <input
                                type="checkbox"
                                id={`pedido-check-${pedidoId}`}
                                className={styles.pedidoCheckbox}
                                checked={isChecked}
                                onChange={(e) => handlePedidoToggle(pedido, e.target.checked)}
                                disabled={saving}
                              />
                              <label
                                htmlFor={`pedido-check-${pedidoId}`}
                                className={styles.pedidoLabel}
                              >
                                Pedido #{pedido.numero}
                              </label>
                            </div>
                            <span className={styles.pedidoSaldo}>
                              {formatCurrency(pedido.saldo_pendiente ?? pedido.monto, pedido.moneda)}
                            </span>
                          </div>

                          {isChecked && (
                            <div className={styles.pedidoExpanded}>
                              <div className={styles.pedidoMontoGroup}>
                                <label className={styles.formLabel}>
                                  Monto a cancelar{isCross ? ` (${form.moneda})` : ''}
                                </label>
                                <div className={isCross ? styles.pedidoMontoInputWrapper : undefined}>
                                  {isCross && (
                                    <span className={styles.pedidoMontoSymbol}>{inputSymbol}</span>
                                  )}
                                  <input
                                    type="number"
                                    step="0.01"
                                    min="0.01"
                                    max={
                                      !isCross
                                        ? (pedido.saldo_pendiente ?? pedido.monto)
                                        : undefined
                                    }
                                    className={styles.inputMonoRight}
                                    value={inputValue}
                                    onChange={(e) =>
                                      isCross
                                        ? handlePedidoMonto(pedidoId, e.target.value, true)
                                        : handlePedidoMonto(pedidoId, e.target.value)
                                    }
                                    onFocus={() =>
                                      isCross &&
                                      setPedidoFocused((prev) => ({ ...prev, [pedidoId]: true }))
                                    }
                                    onBlur={() => {
                                      if (!isCross) return;
                                      setPedidoFocused((prev) => ({ ...prev, [pedidoId]: false }));
                                      // On blur, clear the buffer so display snaps to
                                      // the computed derived value (formatted).
                                      setPedidoOpBuffers((prev) => {
                                        const next = { ...prev };
                                        delete next[pedidoId];
                                        return next;
                                      });
                                    }}
                                    placeholder="0.00"
                                    disabled={saving}
                                    aria-label={`Monto a imputar para pedido ${pedido.numero}${isCross ? ` en ${form.moneda}` : ''}`}
                                  />
                                </div>
                                {nativeRefLine && (
                                  <div className={styles.nativeRefLine}>{nativeRefLine}</div>
                                )}
                              </div>
                              {!isCross && pedido.moneda === form.moneda &&
                                parseFloat(montoActual) >
                                  (pedido.saldo_pendiente ?? pedido.monto) && (
                                <div className={styles.overSaldoHint}>
                                  El monto excede el saldo pendiente. Usá &ldquo;Pago a cuenta&rdquo; para el excedente.
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* T5.5 — Running sum */}
                {items.length > 0 && (
                  <div
                    className={
                      Math.abs(sumaItems - montoTotalNum) < 0.005
                        ? styles.itemsRunningOk
                        : styles.itemsRunningMismatch
                    }
                  >
                    <span>Suma documentos:</span>
                    <strong>{formatCurrency(sumaItems, form.moneda)}</strong>
                    {Math.abs(sumaItems - montoTotalNum) >= 0.005 && (
                      <span className={styles.itemsRunningDiff}>
                        (diferencia con total: {formatCurrency(Math.abs(sumaItems - montoTotalNum), form.moneda)})
                      </span>
                    )}
                  </div>
                )}

                {/* T5.3 / FR-5.2 — Multi-item warning */}
                {itemsSumWarning && items.length > 1 && (
                  <div className={styles.itemsSumWarning} role="alert">
                    <AlertTriangle size={13} style={{ flexShrink: 0 }} />
                    <span>
                      La suma de los items no coincide con el total. Ajustá los montos manualmente
                      o usá pago a cuenta para cubrir la diferencia.
                    </span>
                  </div>
                )}
              </section>

              {/* ── MEDIOS DE PAGO ── */}
              {!isEditMode && form.proveedor_id && (
                <section className={styles.formSection}>
                  <h2 className={styles.sectionHeading}>
                    <CreditCard size={13} className={styles.sectionHeadingIcon} />
                    Medios de pago
                  </h2>

                  {/* F7 — NC como medio de pago */}
                  {/* monedasFiltro: show NCs whose moneda matches any selected pedido's moneda
                      (cross-moneda NCs are valid; filter by OP moneda would hide them). */}
                  <PanelNCsProveedor
                    key={`${form.proveedor_id}-${form.moneda}`}
                    proveedorId={Number(form.proveedor_id)}
                    moneda={form.moneda || undefined}
                    monedasFiltro={(() => {
                      const monedas = new Set(
                        items
                          .filter((it) => it.tipo === 'pedido_compra' && it.id)
                          .map((it) => {
                            const p = pedidoDe(it.id);
                            return p ? p.moneda : null;
                          })
                          .filter(Boolean)
                      );
                      // If no pedidos selected yet, fall back to OP moneda so panel isn't empty.
                      return monedas.size > 0 ? Array.from(monedas) : [form.moneda];
                    })()}
                    opMoneda={form.moneda}
                    mode="seleccionar"
                    onChange={setNcsAplicadas}
                    disabled={saving}
                  />

                  {/* PR4 — Dinero a cuenta */}
                  <div className={styles.dacCard}>
                    <div className={styles.dacCardHeader}>
                      <Wallet size={15} className={styles.dacIcon} />
                      <span className={styles.dacCardTitle}>Dinero a cuenta</span>
                    </div>

                    {loadingDacs ? (
                      <div className={styles.fieldHint}>Cargando saldos disponibles...</div>
                    ) : dacsDisponibles.length === 0 ? (
                      <div className={styles.dacSinSaldo}>
                        Disponible: {formatCurrency(0, form.moneda)} — sin dinero a cuenta para aplicar.
                      </div>
                    ) : (
                      <div className={styles.dacGrid}>
                        <div className={styles.formGroup}>
                          <label className={styles.formLabel}>Saldo disponible</label>
                          <select
                            className={styles.select}
                            value={dacSeleccionado ?? ''}
                            onChange={(e) => {
                              const val = e.target.value;
                              setDacSeleccionado(val ? Number(val) : null);
                              setDacMonto('');
                            }}
                            disabled={saving}
                          >
                            <option value="">Elegí un saldo a cuenta</option>
                            {dacsDisponibles.map((dac) => (
                              <option key={dac.id} value={dac.id}>
                                {formatCurrency(dac.saldo_disponible ?? dac.monto, dac.moneda)}
                                {dac.origen_op_numero ? ` — OP ${dac.origen_op_numero}` : ''}
                              </option>
                            ))}
                          </select>
                        </div>

                        {dacSeleccionado && (() => {
                          const dacItem = dacsDisponibles.find((d) => d.id === dacSeleccionado);
                          const saldoMax = parseFloat(dacItem?.saldo_disponible ?? dacItem?.monto ?? 0);
                          const limitado = Math.min(saldoMax, Math.max(0, diferencia + dacMontoNum));
                          return (
                            <div className={styles.formGroup}>
                              <label className={styles.formLabel}>Monto a usar</label>
                              <input
                                type="number"
                                step="0.01"
                                min="0"
                                max={saldoMax}
                                className={styles.inputMonoRight}
                                value={dacMonto}
                                onChange={(e) => {
                                  setDacMonto(e.target.value);
                                }}
                                placeholder="0.00"
                                disabled={saving}
                              />
                              <div className={styles.fieldHint}>
                                Disponible: {formatCurrency(saldoMax, form.moneda)}.
                                {limitado > 0 && limitado < saldoMax && (
                                  <> Sugerido: {formatCurrency(limitado, form.moneda)} (cubre la diferencia).</>
                                )}
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* ── EXCEDENTE / PAGO A CUENTA ── */}
              {/* Only shown when the user has raised monto_total above net (intentional surplus). */}
              {!isEditMode && montoTotalNum > net && (
                <section className={styles.formSection}>
                  <h2 className={styles.sectionHeadingSmall}>
                    Excedente — Pago a cuenta{' '}
                    <span className={styles.labelHintInline}>
                      (monto que queda disponible para futuras imputaciones de este proveedor)
                    </span>
                  </h2>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={styles.inputMono}
                    value={pagoACuenta}
                    onChange={(e) => {
                      const val = e.target.value;
                      setPagoACuenta(val);
                      // Refinement A: any user gesture (type OR clear) marks as touched.
                      // Auto-fill will no longer override the user's intent.
                      setPagoACuentaTouched(true);
                    }}
                    placeholder="0.00"
                    disabled={saving}
                  />
                </section>
              )}
            </main>

            {/* ══════════════════ RIGHT COLUMN ══════════════════ */}
            <aside className={styles.rightCol}>
              <div className={styles.stickyPanel}>

                {/* ── Resumen de pago card ── */}
                <div className={styles.summaryCard}>
                  <h2 className={styles.summaryHeading}>Resumen de pago</h2>

                  <div className={styles.summaryTotal}>
                    <p className={styles.summaryTotalLabel}>Total a pagar</p>
                    <span className={styles.summaryTotalAmount}>
                      {formatCurrency(montoTotalNum, form.moneda)}
                    </span>
                    {(form.moneda === 'USD' || tieneCrossMoneda) && tcValido && (
                      <span className={styles.summaryTcLine}>
                        TC {form.tipo_cambio} · BNA
                      </span>
                    )}
                  </div>

                  <hr className={styles.summaryDivider} />

                  <div className={styles.summaryRows}>
                    <div className={styles.summaryRow}>
                      <span className={styles.summaryRowLabel}>Pedidos</span>
                      <span className={styles.summaryRowAmount}>{formatCurrency(sumaItems, form.moneda)}</span>
                    </div>
                    {sumaNCsOP > 0 && (
                      <div className={styles.summaryRow}>
                        <span className={styles.summaryRowLabel}>Notas de crédito</span>
                        <span className={`${styles.summaryRowAmount} ${styles.summaryRowNegative}`}>
                          -{formatCurrency(sumaNCsOP, form.moneda)}
                        </span>
                      </div>
                    )}
                    {dacMontoNum > 0 && (
                      <div className={styles.summaryRow}>
                        <span className={styles.summaryRowLabel}>Dinero a cuenta</span>
                        <span className={`${styles.summaryRowAmount} ${styles.summaryRowNegative}`}>
                          -{formatCurrency(dacMontoNum, form.moneda)}
                        </span>
                      </div>
                    )}
                    {pagoACuentaNum > 0 && (
                      <div className={styles.summaryRow}>
                        <span className={styles.summaryRowLabel}>Excedente a cuenta</span>
                        <span className={styles.summaryRowAmount}>{formatCurrency(pagoACuentaNum, form.moneda)}</span>
                      </div>
                    )}
                  </div>

                  <hr className={styles.summaryDivider} />

                  <div className={styles.summaryDiferencia}>
                    <div>
                      <span className={styles.summaryDiferenciaLabel}>Diferencia</span>
                      <span className={styles.summaryDiferenciaAmount}>
                        {formatCurrency(Math.abs(diferencia), form.moneda)}
                      </span>
                    </div>
                    <span className={`${styles.statusPill} ${styles[`statusPill_${diferenciaStatus}`]}`}>
                      {diferenciaStatus === 'ok' && <><Check size={10} /> BALANCEADO</>}
                      {diferenciaStatus === 'falta' && <><AlertTriangle size={10} /> FALTA CUBRIR</>}
                      {diferenciaStatus === 'exceso' && <><AlertTriangle size={10} /> EXCEDENTE</>}
                    </span>
                  </div>
                </div>

                {/* ── Pagar ahora card ── */}
                {!isEditMode && (
                  <div className={styles.pagarAhoraCard}>
                    <div className={styles.pagarAhoraToggleRow}>
                      <span className={styles.pagarAhoraTitle}>
                        <Zap size={14} className={styles.zapIcon} />
                        Pagar ahora
                      </span>
                      <label className={styles.toggleSwitch} aria-label="Pagar ahora">
                        <input
                          type="checkbox"
                          className={styles.toggleInput}
                          checked={pagarAhora}
                          onChange={(e) => setPagarAhora(e.target.checked)}
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                    </div>
                    <p className={styles.pagarAhoraHint}>
                      Al activar, el pago se ejecuta en el mismo momento.
                    </p>

                    {pagarAhora && (
                      <div className={styles.pagarAhoraFields}>
                        <div className={styles.formGroup}>
                          <label className={styles.formLabel}>Fuente de fondos *</label>
                          {loadingCajas || loadingBancosEmpresa ? (
                            <div className={styles.fieldHint}>Cargando fuentes de fondos...</div>
                          ) : (
                            <select
                              className={styles.select}
                              value={pagoForm.fuenteKey}
                              onChange={(e) => handlePagoFormChange('fuenteKey', e.target.value)}
                              required
                            >
                              <option value="">Seleccionar...</option>
                              {cajas.filter((c) => (!form.empresa_id || !c.empresa_id || String(c.empresa_id) === String(form.empresa_id)) && String(c.moneda) === String(form.moneda)).length > 0 && (
                                <optgroup label="Cajas">
                                  {cajas
                                    .filter((c) => (!form.empresa_id || !c.empresa_id || String(c.empresa_id) === String(form.empresa_id)) && String(c.moneda) === String(form.moneda))
                                    .map((c) => (
                                      <option key={`caja:${c.id}`} value={`caja:${c.id}`}>
                                        {c.nombre} — {c.moneda} — saldo:{' '}
                                        {Number(c.saldo_actual || 0).toLocaleString('es-AR', {
                                          minimumFractionDigits: 2,
                                          maximumFractionDigits: 2,
                                        })}
                                      </option>
                                    ))}
                                </optgroup>
                              )}
                              {bancosEmpresa.filter((b) => String(b.moneda) === String(form.moneda)).length > 0 && (
                                <optgroup label="Cuentas bancarias">
                                  {bancosEmpresa
                                    .filter((b) => String(b.moneda) === String(form.moneda))
                                    .map((b) => (
                                    <option key={`banco:${b.id}`} value={`banco:${b.id}`}>
                                      {b.banco} — {b.moneda} — saldo:{' '}
                                      {Number(b.saldo_actual || 0).toLocaleString('es-AR', {
                                        minimumFractionDigits: 2,
                                        maximumFractionDigits: 2,
                                      })}
                                    </option>
                                  ))}
                                </optgroup>
                              )}
                            </select>
                          )}
                        </div>

                        <div className={styles.pagoFormGrid}>
                          <div className={styles.formGroup}>
                            <label className={styles.formLabel}>Fecha de pago *</label>
                            <input
                              type="date"
                              className={styles.select}
                              value={pagoForm.fechaPagoReal}
                              onChange={(e) => handlePagoFormChange('fechaPagoReal', e.target.value)}
                              required
                            />
                          </div>

                          <div className={styles.formGroup}>
                            <label className={styles.formLabel}>
                              TC del pago{' '}
                              <span className={styles.labelHintInline}>(opcional)</span>
                            </label>
                            <input
                              type="number"
                              step="0.0001"
                              min="0"
                              className={styles.inputMonoRight}
                              value={pagoForm.tipoCambioOverride}
                              onChange={(e) => handlePagoFormChange('tipoCambioOverride', e.target.value)}
                              placeholder="Usar TC de la OP"
                            />
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </aside>
          </div>

          {/* ── Footer ── */}
          <footer className={styles.modalFooter}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => onClose(false)}
              disabled={saving}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className={styles.btnSuccess}
              disabled={saving || (pagarAhora && diferencia !== 0)}
            >
              {saving
                ? isEditMode
                  ? 'Guardando...'
                  : pagarAhora
                    ? 'Creando y pagando...'
                    : 'Creando...'
                : isEditMode
                  ? 'Guardar cambios'
                  : pagarAhora
                    ? 'Crear y pagar'
                    : 'Crear OP'}
            </button>
          </footer>
        </form>

        {/* ── Modal de confirmación de duplicado (hijo) ── */}
        {duplicadoInfo && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContentDup}>
              <div className={styles.modalHeader}>
                <div className={styles.headerTitles}>
                  <span className={styles.modalTitle}>
                    Posible duplicado detectado
                  </span>
                </div>
                <button
                  className={styles.modalCloseBtn}
                  onClick={() => setDuplicadoInfo(null)}
                  aria-label="Cerrar"
                  type="button"
                >
                  <X size={18} />
                </button>
              </div>

              <p className={styles.dupMessage}>{duplicadoInfo.mensaje}</p>

              {duplicadoInfo.duplicados.length > 0 ? (
                <div className={styles.dupTableWrapper}>
                  <table className={styles.dupTable}>
                    <thead>
                      <tr>
                        <th>ct_transaction</th>
                        <th>Fecha</th>
                        <th>N° Doc</th>
                        <th className={styles.thRight}>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {duplicadoInfo.duplicados.map((d, i) => (
                        <tr key={i}>
                          <td className={styles.tdMono}>{d.ct_transaction}</td>
                          <td>
                            {d.ct_date ? String(d.ct_date).substring(0, 10) : '—'}
                          </td>
                          <td>{d.ct_docnumber || '—'}</td>
                          <td className={styles.tdRight}>
                            {formatCurrency(d.ct_total, form.moneda)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className={styles.emptyItems}>
                  El backend marcó duplicado pero no envió detalles.
                </div>
              )}

              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setDuplicadoInfo(null)}
                  disabled={submittingConfirm}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  className={styles.btnWarning}
                  onClick={handleConfirmarDuplicado}
                  disabled={submittingConfirm}
                >
                  {submittingConfirm ? 'Guardando...' : 'Confirmar, es un pago distinto'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Modal confirmación cambio de moneda ── */}
        {confirmMoneda && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContentDup}>
              <div className={styles.modalHeader}>
                <div className={styles.headerTitles}>
                  <span className={styles.modalTitle}>
                    Cross-moneda requiere TC
                  </span>
                </div>
                <button
                  className={styles.modalCloseBtn}
                  onClick={() => setConfirmMoneda(null)}
                  aria-label="Cerrar"
                  type="button"
                >
                  <X size={18} />
                </button>
              </div>

              <p className={styles.dupMessage}>
                Estás cambiando la moneda de <strong>{confirmMoneda.from}</strong>{' '}
                a <strong>{confirmMoneda.to}</strong>. Los items pre-cargados van
                a quedar en moneda distinta a la OP: para poder imputarlos vas a
                tener que cargar un <strong>TC &gt; 0</strong> en el campo "Tipo
                de cambio" antes de guardar. Los items se mantienen.
              </p>

              <div className={styles.formActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setConfirmMoneda(null)}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  className={styles.btnWarning}
                  onClick={handleConfirmMoneda}
                >
                  Continuar (voy a cargar TC)
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
