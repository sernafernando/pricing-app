import { useCallback, useEffect, useState } from 'react';
import { X, AlertTriangle, Check, Plus, Trash2, Zap, Wallet } from 'lucide-react';
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

const TIPOS_ITEM = [
  { value: 'pedido_compra', label: 'Pedido de compra' },
  { value: 'factura_erp', label: 'Factura ERP' },
];

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
      setBancosEmpresa(Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : []);
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

  // ── Modo imputación derivado de los items ──
  // 0 items         → a_cuenta
  // items, suma === total → especifica
  // items, suma < total  → mixta
  // (suma > total es inválido — validar() lo bloquea)
  // PR3: pago_a_cuenta se trata como item de cobertura para derivar el modo.
  const derivarModoImputacion = (currentItems, total, pacNum = 0) => {
    const hasPac = pacNum > 0;
    if (currentItems.length === 0 && !hasPac) return 'a_cuenta';
    const sumaDoc = Math.round(
      currentItems.reduce((acc, it) => acc + (parseFloat(it.monto) || 0), 0) * 100
    ) / 100;
    const sumaTotal = Math.round((sumaDoc + pacNum) * 100) / 100;
    const totalR = Math.round((parseFloat(total) || 0) * 100) / 100;
    // Si hay items de documento y también pago_a_cuenta → mixta (hay mezcla de destinos)
    if (currentItems.length > 0 && hasPac) return 'mixta';
    return sumaTotal >= totalR ? 'especifica' : 'mixta';
  };

  const modoImputacion = derivarModoImputacion(items, form.monto_total, pagoACuentaNum);

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
        // Convertimos el monto si hay TC (mantiene UX previa).
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

  const addItem = () => {
    setItems((prev) => [
      ...prev,
      { tipo: 'pedido_compra', id: '', monto: '', numero_factura: '' },
    ]);
  };

  const removeItem = (idx) => {
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateItem = (idx, campo, valor) => {
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, [campo]: valor } : it))
    );
  };

  // ── Validación ──
  const sumaItems = items.reduce((acc, it) => acc + (parseFloat(it.monto) || 0), 0);
  const montoTotalNum = parseFloat(form.monto_total) || 0;

  // PR3/PR4 — Cobertura total y diferencia en vivo.
  // cobertura = sum(items documentos) + sum(NCs aplicadas) + pagoACuenta + DAC.
  const sumaNCs = ncsAplicadas.reduce((acc, nc) => acc + (parseFloat(nc.monto) || 0), 0);
  const coberturaTotal = sumaItems + sumaNCs + pagoACuentaNum + dacMontoNum;
  const diferencia = Math.round((montoTotalNum - coberturaTotal) * 100) / 100;

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
        ...items.map((it) => ({
          tipo: it.tipo,
          id: it.id ? Number(it.id) : null,
          monto: parseFloat(it.monto),
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
      ncs_aplicadas: isEditMode ? [] : ncsAplicadas,
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
    items: items.map((it) => ({
      tipo: it.tipo,
      id: it.id ? Number(it.id) : null,
      monto: parseFloat(it.monto),
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
        setError(res?.data?.detail || 'Error al crear la OP.');
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

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            {isEditMode ? `Editar OP ${op.numero}` : 'Nueva Orden de Pago'}
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

        {/* Banner anti-doble-contabilización */}
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

        <form onSubmit={handleSubmit}>
          <div className={styles.formRow}>
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

          <div className={styles.formRow}>
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
                className={styles.input}
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
                className={`${styles.input}${tcError ? ` ${styles.inputError}` : ''}`}
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

          {/* F3 — "Pagar ahora" toggle (solo en creación) */}
          {!isEditMode && (
            <div className={styles.formGroupCheckbox}>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  className={styles.checkbox}
                  checked={pagarAhora}
                  onChange={(e) => setPagarAhora(e.target.checked)}
                />
                <Zap size={14} style={{ marginLeft: 4, marginRight: 4 }} />
                <span>Pagar ahora (crear y pagar en un solo paso)</span>
              </label>
              <div className={styles.fieldHint}>
                Al activar esta opción se ejecuta el pago en el mismo momento.
                Si no, la OP queda en estado pendiente para pagar después.
              </div>
            </div>
          )}

          {/* F3 — inline payment fields (visible when "Pagar ahora" is ON) */}
          {!isEditMode && pagarAhora && (
            <div className={styles.pagarAhoraPanel}>
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
                    {cajas.filter((c) => !form.empresa_id || !c.empresa_id || String(c.empresa_id) === String(form.empresa_id)).length > 0 && (
                      <optgroup label="Cajas">
                        {cajas
                          .filter((c) => !form.empresa_id || !c.empresa_id || String(c.empresa_id) === String(form.empresa_id))
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
                    {bancosEmpresa.length > 0 && (
                      <optgroup label="Cuentas bancarias">
                        {bancosEmpresa.map((b) => (
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

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Fecha pago real *</label>
                <input
                  type="date"
                  className={styles.input}
                  value={pagoForm.fechaPagoReal}
                  onChange={(e) => handlePagoFormChange('fechaPagoReal', e.target.value)}
                  required
                />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>
                  TC al momento del pago{' '}
                  <span className={styles.labelHintInline}>(opcional — sobrescribe el TC de la OP)</span>
                </label>
                <input
                  type="number"
                  step="0.0001"
                  min="0"
                  className={styles.input}
                  value={pagoForm.tipoCambioOverride}
                  onChange={(e) => handlePagoFormChange('tipoCambioOverride', e.target.value)}
                  placeholder="Dejar vacío para usar TC de la OP"
                />
              </div>
            </div>
          )}

          {/* Tabla de items — siempre visible; modo_imputacion se deriva de los items */}
          <div className={styles.itemsSection}>
              <div className={styles.itemsHeader}>
                <h4 className={styles.itemsTitle}>Items imputados</h4>
                <div className={styles.itemsSummary}>
                  <span>Imputado: {formatCurrency(sumaItems, form.moneda)}</span>
                  <span> / Total: {formatCurrency(montoTotalNum, form.moneda)}</span>
                  <span className={styles.itemsRemanente}>
                    Remanente:{' '}
                    {formatCurrency(Math.max(0, montoTotalNum - sumaItems), form.moneda)}
                  </span>
                </div>
                <button
                  type="button"
                  className={styles.btnPrimary}
                  onClick={addItem}
                >
                  <Plus size={14} /> Agregar
                </button>
              </div>
              {items.length === 0 ? (
                <div className={styles.emptyItems}>
                  Agregá items para imputar el pago a pedidos/facturas específicas.
                </div>
              ) : (
                <div className={styles.itemsTableWrapper}>
                  <table className={styles.itemsTable}>
                    <thead>
                      <tr>
                        <th>Tipo</th>
                        <th>ID</th>
                        <th className={styles.thRight}>Monto</th>
                        <th>N° Factura</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((it, idx) => {
                        // Auto-sugerir monto al elegir pedido del dropdown.
                        const handleSelectPedido = (valorId) => {
                          if (!valorId) {
                            updateItem(idx, 'id', '');
                            return;
                          }
                          const pedido = pendientesDelProveedor.find(
                            (p) => String(p.id) === String(valorId)
                          );
                          setItems((prev) =>
                            prev.map((row, i) =>
                              i === idx
                                ? {
                                    ...row,
                                    id: valorId,
                                    monto: pedido
                                      ? String(pedido.saldo_pendiente ?? pedido.monto)
                                      : row.monto,
                                    numero_factura:
                                      pedido?.numero_factura || row.numero_factura,
                                  }
                                : row
                            )
                          );
                        };
                        return (
                          <tr key={idx}>
                            <td>
                              <select
                                className={styles.selectSmall}
                                value={it.tipo}
                                onChange={(e) => updateItem(idx, 'tipo', e.target.value)}
                              >
                                {TIPOS_ITEM.map((t) => (
                                  <option key={t.value} value={t.value}>
                                    {t.label}
                                  </option>
                                ))}
                              </select>
                            </td>
                            <td>
                              {it.tipo === 'pedido_compra' ? (
                                <select
                                  className={styles.selectSmall}
                                  value={it.id}
                                  onChange={(e) => handleSelectPedido(e.target.value)}
                                >
                                  <option value="">Seleccionar pedido...</option>
                                  {pedidosDisponibles
                                    .filter(
                                      (p) =>
                                        String(p.id) === String(it.id) ||
                                        !idsPedidosYaAgregados.has(String(p.id))
                                    )
                                    .map((p) => (
                                      <option key={p.id} value={p.id}>
                                        {p.numero} — {formatCurrency(
                                          p.saldo_pendiente ?? p.monto,
                                          p.moneda
                                        )}
                                      </option>
                                    ))}
                                </select>
                              ) : (
                                <input
                                  type="number"
                                  className={styles.inputSmall}
                                  value={it.id}
                                  onChange={(e) => updateItem(idx, 'id', e.target.value)}
                                  placeholder="ct_transaction_id"
                                />
                              )}
                            </td>
                            <td>
                              <input
                                type="number"
                                step="0.01"
                                min="0.01"
                                className={styles.inputSmallRight}
                                value={it.monto}
                                onChange={(e) => updateItem(idx, 'monto', e.target.value)}
                                placeholder="0.00"
                              />
                              {(() => {
                                // Preview de conversión cross-moneda por item.
                                // Solo si: el item es pedido_compra, su moneda
                                // difiere de la OP, hay TC válido y monto > 0.
                                if (it.tipo !== 'pedido_compra' || !it.id) return null;
                                const pedidoItem = pedidoDe(it.id);
                                if (!pedidoItem || pedidoItem.moneda === form.moneda) {
                                  return null;
                                }
                                if (!tcValido) return null;
                                const montoItem = parseFloat(it.monto);
                                if (!Number.isFinite(montoItem) || montoItem <= 0) {
                                  return null;
                                }
                                // OP ARS pagando pedido USD → monto_item / TC = USD destino.
                                // OP USD pagando pedido ARS → monto_item * TC = ARS destino.
                                const convertido =
                                  form.moneda === 'ARS' && pedidoItem.moneda === 'USD'
                                    ? montoItem / tcNumLive
                                    : form.moneda === 'USD' && pedidoItem.moneda === 'ARS'
                                      ? montoItem * tcNumLive
                                      : null;
                                if (convertido === null) return null;
                                const op = formatCurrency(montoItem, form.moneda);
                                const dest = formatCurrency(convertido, pedidoItem.moneda);
                                // Símbolo de operación según dirección.
                                const opSign =
                                  form.moneda === 'ARS' && pedidoItem.moneda === 'USD'
                                    ? '÷'
                                    : '×';
                                return (
                                  <div className={styles.previewConversion}>
                                    {op} {opSign} TC {tcNumLive} = {dest}
                                  </div>
                                );
                              })()}
                            </td>
                            <td>
                              <input
                                type="text"
                                className={styles.inputSmall}
                                value={it.numero_factura}
                                onChange={(e) =>
                                  updateItem(idx, 'numero_factura', e.target.value)
                                }
                                placeholder="FA-..."
                                maxLength={50}
                              />
                            </td>
                            <td>
                              <button
                                type="button"
                                className={styles.iconBtnDanger}
                                onClick={() => removeItem(idx)}
                                aria-label="Quitar item"
                              >
                                <Trash2 size={12} />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

          {/* PR4 — Sección "Medios de pago" (NC + dinero a cuenta) */}
          {!isEditMode && form.proveedor_id && (
            <div className={styles.mediosPagoSection}>
              <div className={styles.mediosPagoHeader}>
                <Wallet size={14} className={styles.mediosPagoIcon} />
                <span className={styles.mediosPagoTitle}>Medios de pago (cobertura adicional)</span>
              </div>

              {/* F7 — NC como medio de pago documental */}
              <PanelNCsProveedor
                key={`${form.proveedor_id}-${form.moneda}`}
                proveedorId={Number(form.proveedor_id)}
                moneda={form.moneda || undefined}
                mode="seleccionar"
                onChange={setNcsAplicadas}
                disabled={saving}
              />

              {/* PR4 — Dinero a cuenta como medio de pago (real money) */}
              <div className={styles.dacSection}>
                <label className={styles.dacLabel}>
                  Dinero a cuenta{' '}
                  <span className={styles.labelHintInline}>(saldo real disponible del proveedor)</span>
                </label>
                {loadingDacs ? (
                  <div className={styles.fieldHint}>Cargando saldos disponibles...</div>
                ) : dacsDisponibles.length === 0 ? (
                  <div className={styles.dacSinSaldo}>
                    Disponible: {formatCurrency(0, form.moneda)} — sin dinero a cuenta para aplicar.
                  </div>
                ) : (
                  <div className={styles.dacControls}>
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
                      <option value="">Seleccionar dinero a cuenta...</option>
                      {dacsDisponibles.map((dac) => (
                        <option key={dac.id} value={dac.id}>
                          {formatCurrency(dac.saldo_disponible ?? dac.monto, dac.moneda)}
                          {dac.origen_op_numero ? ` — OP ${dac.origen_op_numero}` : ''}
                        </option>
                      ))}
                    </select>
                    {dacSeleccionado && (() => {
                      const dacItem = dacsDisponibles.find((d) => d.id === dacSeleccionado);
                      const saldoMax = parseFloat(dacItem?.saldo_disponible ?? dacItem?.monto ?? 0);
                      const limitado = Math.min(saldoMax, Math.max(0, diferencia + dacMontoNum));
                      return (
                        <div className={styles.dacMontoRow}>
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            max={saldoMax}
                            className={styles.input}
                            value={dacMonto}
                            onChange={(e) => setDacMonto(e.target.value)}
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
            </div>
          )}

          {/* PR3 — Pago a cuenta + indicador de diferencia */}
          {!isEditMode && (
            <div className={styles.pagoACuentaSection}>
              <label className={styles.label}>
                Pago a cuenta{' '}
                <span className={styles.labelHintInline}>
                  (dinero disponible sin imputación a pedido específico)
                </span>
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                className={styles.input}
                value={pagoACuenta}
                onChange={(e) => setPagoACuenta(e.target.value)}
                placeholder="0.00"
                disabled={saving}
              />
              {diferencia !== 0 && (
                <div
                  className={
                    diferencia > 0 ? styles.diferenciaPositiva : styles.diferenciaNegativa
                  }
                >
                  <AlertTriangle size={14} style={{ marginRight: 4, flexShrink: 0 }} />
                  {diferencia > 0
                    ? `Faltan cubrir ${formatCurrency(diferencia, form.moneda)} — sumá items o asigná pago a cuenta.`
                    : `Exceso de ${formatCurrency(Math.abs(diferencia), form.moneda)} — la cobertura supera el total.`}
                </div>
              )}
              {diferencia === 0 && coberturaTotal > 0 && (
                <div className={styles.diferenciaOk}><Check size={14} /> Cobertura completa</div>
              )}
            </div>
          )}

          <div className={styles.formActions}>
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
          </div>
        </form>

        {/* Modal de confirmación de duplicado (hijo) */}
        {duplicadoInfo && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContentDup}>
              <div className={styles.modalHeader}>
                <span className={styles.modalTitle}>
                  <AlertTriangle
                    size={18}
                    style={{ verticalAlign: 'middle', marginRight: 6 }}
                  />
                  Posible duplicado detectado
                </span>
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

        {/* Modal confirmación cambio de moneda destructivo */}
        {confirmMoneda && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContentDup}>
              <div className={styles.modalHeader}>
                <span className={styles.modalTitle}>
                  <AlertTriangle
                    size={18}
                    style={{ verticalAlign: 'middle', marginRight: 6 }}
                  />
                  Cross-moneda requiere TC
                </span>
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
