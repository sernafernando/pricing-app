import { useCallback, useEffect, useState } from 'react';
import {
  X,
  ChevronDown,
  Info,
  Clock,
  Loader2,
  Send,
} from 'lucide-react';
import api from '../../services/api';
import useCheques from '../../hooks/useCheques';
import ProveedorComprasAutocomplete from './ProveedorComprasAutocomplete';
import styles from './ModalCheque.module.css';

/**
 * ModalCheque — emisión de cheque propio (Slice 1).
 *
 * Modos:
 *   mode="standalone" (default): cierra con onClose(true) al emitir.
 *   mode="op": usado desde ModalOrdenPagoNueva. En lugar de llamar al backend
 *              directamente, llama onEmitido(chequePayload) con los datos
 *              del cheque para que el modal padre los incluya en el submit.
 *              NO llama al backend — la OP los emite en la misma transacción.
 *
 * Props:
 *   onClose   (bool) => void  — siempre presente.
 *   mode      "standalone" | "op"
 *   onEmitido (payload) => void — solo en mode="op".
 *   proveedorId  number — pre-carga beneficiario (desde OP).
 *   empresaId    number — filtra bancos de empresa.
 *
 * RULE: NO cierra con click en overlay (AGENTS.md: solo X o Cancelar).
 *
 * Slice 2: agrega modo "tercero":
 *   - Campos: banco_nombre (texto), cuit_librador (texto), librador_nombre (texto opt).
 *   - En mode="standalone": llama recibirTercero → crea en_cartera.
 *   - En mode="op": llama onEmitido(payload) con los datos (sin cheque_id — el
 *     modal de cartera es quien provee cheque_id para endoso). El padre decide
 *     si va a backend como emisión nueva de tercero o como endoso existente.
 */

const today = () => {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const diffDias = (fechaEmision, fechaPago) => {
  if (!fechaEmision || !fechaPago) return 0;
  const a = new Date(fechaEmision);
  const b = new Date(fechaPago);
  return Math.round((b - a) / (1000 * 60 * 60 * 24));
};

export default function ModalCheque({
  onClose,
  mode = 'standalone',
  onEmitido,
  proveedorId: proveedorIdProp = null,
  empresaId: empresaIdProp = null,
}) {
  const { emitirPropio, recibirTercero, listarChequeras, loading: saving, error: hookError } = useCheques();

  // FIX 4: guard against double-submit in mode="op" (isSaving only covers standalone).
  const [submitting, setSubmitting] = useState(false);

  // ── Empresas (standalone: elegir empresa para poder filtrar sus bancos) ──
  const [empresas, setEmpresas] = useState([]);
  const [empresaSel, setEmpresaSel] = useState(empresaIdProp ? String(empresaIdProp) : '');

  // ── Bancos de empresa ──
  const [bancosEmpresa, setBancosEmpresa] = useState([]);
  const [loadingBancos, setLoadingBancos] = useState(false);

  const fetchBancos = useCallback(async (empId) => {
    if (!empId) return;
    setLoadingBancos(true);
    try {
      const { data } = await api.get(
        `/administracion/bancos?solo_activos=true&empresa_id=${empId}`,
      );
      setBancosEmpresa(
        Array.isArray(data?.bancos) ? data.bancos : Array.isArray(data) ? data : [],
      );
    } catch {
      setBancosEmpresa([]);
    } finally {
      setLoadingBancos(false);
    }
  }, []);

  // Empresa efectiva: la de la OP (prop) o la elegida en modo standalone.
  const effectiveEmpresaId = empresaIdProp ?? (empresaSel ? Number(empresaSel) : null);

  // Standalone: cargar la lista de empresas para el selector.
  useEffect(() => {
    if (empresaIdProp) return;
    api
      .get('/admin/empresas')
      .then(({ data }) => setEmpresas(Array.isArray(data) ? data : data?.empresas ?? []))
      .catch(() => setEmpresas([]));
  }, [empresaIdProp]);

  // Cargar bancos cada vez que cambia la empresa efectiva (prop o elegida).
  useEffect(() => {
    if (effectiveEmpresaId) fetchBancos(effectiveEmpresaId);
    else setBancosEmpresa([]);
  }, [effectiveEmpresaId, fetchBancos]);

  // ── Chequeras ──
  const [chequeras, setChequeras] = useState([]);
  const [loadingChequeras, setLoadingChequeras] = useState(false);

  const fetchChequeras = useCallback(
    async (bancoEmpresaId) => {
      if (!bancoEmpresaId) {
        setChequeras([]);
        return;
      }
      setLoadingChequeras(true);
      try {
        const result = await listarChequeras({ banco_empresa_id: bancoEmpresaId });
        const items = result?.items ?? (Array.isArray(result) ? result : []);
        setChequeras(items.filter((c) => c.activa));
      } catch {
        setChequeras([]);
      } finally {
        setLoadingChequeras(false);
      }
    },
    [listarChequeras],
  );

  // ── Form state ──
  // In mode="op" only "propio" is allowed — tercero alta goes to standalone (TabCheques).
  // Third-party cheques are added to the OP via "Endosar de cartera" in PanelCheques.
  const [tipo, setTipo] = useState('propio');
  const [instrumento, setInstrumento] = useState('fisico');
  // propio
  const [bancoEmpresaId, setBancoEmpresaId] = useState('');
  const [chequeraId, setChequeraId] = useState('');
  // tercero
  const [bancoNombre, setBancoNombre] = useState('');
  const [cuitLibrador, setCuitLibrador] = useState('');
  const [libradorNombre, setLibradorNombre] = useState('');
  // comunes
  const [numero, setNumero] = useState('');
  const [proveedorId, setProveedorId] = useState(proveedorIdProp ? String(proveedorIdProp) : '');
  const [monto, setMonto] = useState('');
  const [moneda, setMoneda] = useState('ARS');
  const [fechaEmision, setFechaEmision] = useState(today());
  const [fechaPago, setFechaPago] = useState(today());
  const [error, setError] = useState(null);

  // Reset campos al cambiar de tipo.
  const handleSetTipo = (t) => {
    setTipo(t);
    setError(null);
    setNumero('');
    setMonto('');
    setFechaEmision(today());
    setFechaPago(today());
    // reset propio
    setBancoEmpresaId('');
    setChequeraId('');
    setChequeras([]);
    // reset tercero
    setBancoNombre('');
    setCuitLibrador('');
    setLibradorNombre('');
  };

  // Auto-populate proveedor cuando cambia la prop (modo OP).
  useEffect(() => {
    if (proveedorIdProp) setProveedorId(String(proveedorIdProp));
  }, [proveedorIdProp]);

  // Cuando se elige banco, cargar chequeras y resetear chequera/numero.
  useEffect(() => {
    setChequeraId('');
    setNumero('');
    setChequeras([]);
    if (bancoEmpresaId) fetchChequeras(bancoEmpresaId);
  }, [bancoEmpresaId, fetchChequeras]);

  // Cuando se elige chequera, auto-llenar el próximo número.
  useEffect(() => {
    if (!chequeraId) {
      setNumero('');
      return;
    }
    const chequera = chequeras.find((c) => String(c.id) === String(chequeraId));
    if (chequera?.proximo_numero != null) {
      setNumero(String(chequera.proximo_numero).padStart(8, '0'));
    }
  }, [chequeraId, chequeras]);

  // ── Derived: diferido ──
  const dias = diffDias(fechaEmision, fechaPago);
  const esDiferido = dias > 0;

  // ── Derived: resumen ──
  const bancoNombreResumen = tipo === 'propio'
    ? (bancosEmpresa.find((b) => String(b.id) === String(bancoEmpresaId))?.banco ?? '—')
    : (bancoNombre.trim() || '—');

  // ── Validación ──
  const validarCuit = (v) => /^\d{2}-\d{8}-\d$/.test(v.trim()) || /^\d{11}$/.test(v.trim());

  const validar = () => {
    if (tipo === 'propio') {
      if (!effectiveEmpresaId) return 'Seleccioná una empresa.';
      if (!bancoEmpresaId) return 'Seleccioná un banco.';
      if (instrumento === 'fisico' && !chequeraId) return 'Seleccioná una chequera.';
      if (!proveedorId) return 'El beneficiario es requerido.';
    } else {
      if (!bancoNombre.trim()) return 'El nombre del banco es requerido.';
      if (!cuitLibrador.trim()) return 'El CUIT del librador es requerido.';
      if (!validarCuit(cuitLibrador)) return 'El CUIT debe tener formato XX-XXXXXXXX-X o 11 dígitos.';
    }
    if (!numero.trim()) return 'El número de cheque es requerido.';
    const montoNum = parseFloat(monto);
    if (!Number.isFinite(montoNum) || montoNum <= 0) return 'El monto debe ser mayor a 0.';
    if (!fechaEmision) return 'La fecha de emisión es requerida.';
    if (!fechaPago) return 'La fecha de pago es requerida.';
    if (dias < 0) return 'La fecha de pago no puede ser anterior a la de emisión.';
    return null;
  };

  const buildPayload = () => {
    if (tipo === 'propio') {
      return {
        banco_empresa_id: Number(bancoEmpresaId),
        chequera_id: instrumento === 'fisico' && chequeraId ? Number(chequeraId) : null,
        instrumento,
        numero: numero.trim(),
        monto: parseFloat(monto),
        moneda,
        fecha_emision: fechaEmision,
        fecha_pago: fechaPago,
        proveedor_id: Number(proveedorId),
      };
    }
    // tercero
    return {
      banco_nombre: bancoNombre.trim(),
      cuit_librador: cuitLibrador.trim(),
      ...(libradorNombre.trim() ? { librador_nombre: libradorNombre.trim() } : {}),
      instrumento,
      numero: numero.trim(),
      monto: parseFloat(monto),
      moneda,
      fecha_emision: fechaEmision,
      fecha_pago: fechaPago,
    };
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return; // FIX 4: prevent double-submit in mode="op"
    const v = validar();
    if (v) {
      setError(v);
      return;
    }
    setError(null);

    const payload = buildPayload();

    if (mode === 'op') {
      // En modo OP no vamos al backend: el padre lo emite en la misma TX.
      setSubmitting(true);
      onEmitido?.(payload);
      return;
    }

    // Modo standalone: llamar al backend.
    try {
      if (tipo === 'propio') {
        await emitirPropio(payload);
      } else {
        await recibirTercero(payload);
      }
      onClose(true);
    } catch (err) {
      const d = err.response?.data;
      const msg =
        (typeof d?.detail === 'string' && d.detail) ||
        d?.mensaje ||
        err.message ||
        'Error al procesar el cheque.';
      setError(typeof msg === 'string' ? msg : 'Error al procesar el cheque.');
    }
  };

  const isSaving = (saving && mode === 'standalone') || submitting;
  const titleText = tipo === 'tercero' ? 'Recibir cheque de tercero' : 'Emitir cheque propio';

  return (
    <div className={styles.overlay}>
      <div className={styles.container} role="dialog" aria-modal="true" aria-labelledby="modal-cheque-title">

        {/* Header */}
        <header className={styles.header}>
          <h2 id="modal-cheque-title" className={styles.title}>{titleText}</h2>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={() => onClose(false)}
            aria-label="Cerrar"
          >
            <X size={18} />
          </button>
        </header>

        {/* Body */}
        <div className={styles.body}>
          {(error || hookError) && (
            <div className={styles.errorBanner} role="alert">
              {error || hookError}
            </div>
          )}

          <form id="form-cheque" onSubmit={handleSubmit}>

            {/* Tipo de cheque (segmented) — in mode="op" only "propio" is available */}
            {mode !== 'op' && (
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Tipo de cheque</label>
                <div className={styles.segmented}>
                  <button
                    type="button"
                    className={`${styles.segBtn} ${tipo === 'propio' ? styles.segBtnActive : ''}`}
                    onClick={() => handleSetTipo('propio')}
                    disabled={isSaving}
                  >
                    Propio
                  </button>
                  <button
                    type="button"
                    className={`${styles.segBtn} ${tipo === 'tercero' ? styles.segBtnActive : ''}`}
                    onClick={() => handleSetTipo('tercero')}
                    disabled={isSaving}
                  >
                    De tercero
                  </button>
                </div>
              </div>
            )}

            {/* Instrumento (pills) */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Instrumento</label>
              <div className={styles.pills}>
                <button
                  type="button"
                  className={`${styles.pill} ${instrumento === 'fisico' ? styles.pillActive : ''}`}
                  onClick={() => {
                    setInstrumento('fisico');
                    setNumero('');
                    // For propio+físico the chequera useEffect re-fills the number automatically.
                  }}
                >
                  Físico
                </button>
                <button
                  type="button"
                  className={`${styles.pill} ${instrumento === 'echeq' ? styles.pillActive : ''}`}
                  onClick={() => {
                    setInstrumento('echeq');
                    setNumero(''); // e-cheq requires manual bank number — clear any autocomplete.
                  }}
                >
                  e-cheq
                </button>
              </div>
            </div>

            {/* Campos específicos: propio vs tercero */}
            {tipo === 'propio' && (
              <>
                {/* Empresa — solo standalone; en modo OP se hereda de la OP. */}
                {!empresaIdProp && (
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel} htmlFor="cheque-empresa">
                      Empresa
                    </label>
                    <div className={styles.selectWrapper}>
                      <select
                        id="cheque-empresa"
                        className={styles.select}
                        value={empresaSel}
                        onChange={(e) => {
                          setEmpresaSel(e.target.value);
                          setBancoEmpresaId('');
                          setChequeraId('');
                        }}
                        required
                        disabled={isSaving}
                      >
                        <option value="">Seleccioná una empresa...</option>
                        {empresas.map((emp) => (
                          <option key={emp.id} value={emp.id}>
                            {emp.nombre}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={14} className={styles.selectArrow} />
                    </div>
                  </div>
                )}

                {/* Banco (select empresa) */}
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel} htmlFor="cheque-banco">
                    Banco
                  </label>
                  {loadingBancos ? (
                    <div className={styles.loadingRow}>
                      <Loader2 size={14} className={styles.spin} /> Cargando bancos...
                    </div>
                  ) : !effectiveEmpresaId ? (
                    <p className={styles.fieldHint}>
                      Elegí una empresa para ver sus bancos.
                    </p>
                  ) : bancosEmpresa.length === 0 ? (
                    <p className={styles.fieldHint}>
                      La empresa seleccionada no tiene bancos activos.
                    </p>
                  ) : (
                    <div className={styles.selectWrapper}>
                      <select
                        id="cheque-banco"
                        className={styles.select}
                        value={bancoEmpresaId}
                        onChange={(e) => setBancoEmpresaId(e.target.value)}
                        required
                        disabled={isSaving}
                      >
                        <option value="">Seleccioná un banco...</option>
                        {bancosEmpresa.map((b) => (
                          <option key={b.id} value={b.id}>
                            {b.banco} — {b.tipo_cuenta ?? 'Cuenta corriente'} {b.moneda ?? ''}{' '}
                            {b.numero_cuenta ? `(${b.numero_cuenta})` : ''}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={14} className={styles.selectArrow} />
                    </div>
                  )}
                </div>
              </>
            )}

            {tipo === 'tercero' && (
              <>
                {/* Banco nombre (texto libre) */}
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel} htmlFor="cheque-banco-nombre">
                    Banco
                  </label>
                  <input
                    id="cheque-banco-nombre"
                    type="text"
                    className={styles.inputMono}
                    value={bancoNombre}
                    onChange={(e) => setBancoNombre(e.target.value)}
                    placeholder="Ej: Banco Nación"
                    required
                    disabled={isSaving}
                  />
                </div>

                {/* CUIT librador + Nombre librador (grid 2) */}
                <div className={styles.grid2}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel} htmlFor="cheque-cuit">
                      CUIT librador
                    </label>
                    <input
                      id="cheque-cuit"
                      type="text"
                      className={styles.inputMono}
                      value={cuitLibrador}
                      onChange={(e) => setCuitLibrador(e.target.value)}
                      placeholder="XX-XXXXXXXX-X"
                      required
                      disabled={isSaving}
                    />
                    <p className={styles.fieldHint}>Formato: 20-12345678-9 o 11 dígitos</p>
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel} htmlFor="cheque-librador">
                      Librador (opcional)
                    </label>
                    <input
                      id="cheque-librador"
                      type="text"
                      className={styles.inputMono}
                      value={libradorNombre}
                      onChange={(e) => setLibradorNombre(e.target.value)}
                      placeholder="Razón social o nombre"
                      disabled={isSaving}
                    />
                  </div>
                </div>
              </>
            )}

            {/* Chequera + Número (grid 2 cols) — solo propio+físico */}
            {tipo === 'propio' && instrumento === 'fisico' && (
              <div className={styles.grid2}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel} htmlFor="cheque-chequera">
                    Chequera
                  </label>
                  {loadingChequeras ? (
                    <div className={styles.loadingRow}>
                      <Loader2 size={14} className={styles.spin} />
                    </div>
                  ) : (
                    <div className={styles.selectWrapper}>
                      <select
                        id="cheque-chequera"
                        className={styles.select}
                        value={chequeraId}
                        onChange={(e) => setChequeraId(e.target.value)}
                        disabled={!bancoEmpresaId || isSaving}
                        required
                      >
                        <option value="">Seleccioná...</option>
                        {chequeras.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.descripcion || `Chequera ${c.id}`}
                            {c.numero_desde != null && c.numero_hasta != null
                              ? ` (${String(c.numero_desde).padStart(8, '0')}–${String(c.numero_hasta).padStart(8, '0')})`
                              : ''}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={14} className={styles.selectArrow} />
                    </div>
                  )}
                </div>

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel} htmlFor="cheque-numero">
                    Número de cheque
                  </label>
                  <input
                    id="cheque-numero"
                    type="text"
                    className={styles.inputMono}
                    value={numero}
                    onChange={(e) => setNumero(e.target.value)}
                    placeholder="00000000"
                    required
                    disabled={isSaving}
                  />
                  <p className={styles.fieldHint}>Número real impreso en el talón</p>
                </div>
              </div>
            )}

            {/* e-cheq o tercero+físico: número standalone */}
            {(instrumento === 'echeq' || (tipo === 'tercero' && instrumento === 'fisico')) && (
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel} htmlFor="cheque-numero-echeq">
                  {instrumento === 'echeq' ? 'Número e-cheq' : 'Número de cheque'}
                </label>
                <input
                  id="cheque-numero-echeq"
                  type="text"
                  className={styles.inputMono}
                  value={numero}
                  onChange={(e) => setNumero(e.target.value)}
                  placeholder={instrumento === 'echeq' ? 'Número del banco' : '00000000'}
                  required
                  disabled={isSaving}
                />
                {instrumento === 'fisico' && (
                  <p className={styles.fieldHint}>Número impreso en el cheque</p>
                )}
              </div>
            )}

            {/* Beneficiario (solo cheques propios) */}
            {tipo === 'propio' && (
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Beneficiario</label>
                <ProveedorComprasAutocomplete
                  value={proveedorId ? Number(proveedorId) : null}
                  onChange={(id) => setProveedorId(id ? String(id) : '')}
                  disabled={isSaving}
                />
              </div>
            )}

            {/* Monto + Moneda (grid 3 cols: monto ocupa 2) */}
            <div className={styles.grid3}>
              <div className={`${styles.fieldGroup} ${styles.colSpan2}`}>
                <label className={styles.fieldLabel} htmlFor="cheque-monto">
                  Monto
                </label>
                <div className={styles.montoWrapper}>
                  <span className={styles.montoPrefix}>{moneda === 'USD' ? 'US$' : '$'}</span>
                  <input
                    id="cheque-monto"
                    type="number"
                    step="0.01"
                    min="0.01"
                    className={styles.montoInput}
                    value={monto}
                    onChange={(e) => setMonto(e.target.value)}
                    placeholder="0,00"
                    required
                    disabled={isSaving}
                  />
                </div>
              </div>

              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel} htmlFor="cheque-moneda">
                  Moneda
                </label>
                <div className={styles.selectWrapper}>
                  <select
                    id="cheque-moneda"
                    className={styles.select}
                    value={moneda}
                    onChange={(e) => setMoneda(e.target.value)}
                    disabled={isSaving}
                  >
                    <option value="ARS">ARS</option>
                    <option value="USD">USD</option>
                  </select>
                  <ChevronDown size={14} className={styles.selectArrow} />
                </div>
              </div>
            </div>

            {/* Fechas (grid 2 cols) */}
            <div className={styles.grid2}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel} htmlFor="cheque-fecha-emision">
                  Fecha de emisión
                </label>
                <input
                  id="cheque-fecha-emision"
                  type="date"
                  className={styles.inputMono}
                  value={fechaEmision}
                  onChange={(e) => setFechaEmision(e.target.value)}
                  required
                  disabled={isSaving}
                />
              </div>

              <div className={styles.fieldGroup}>
                <div className={styles.fechaPagoHeader}>
                  <label className={styles.fieldLabel} htmlFor="cheque-fecha-pago">
                    Fecha de pago
                  </label>
                  {esDiferido && (
                    <span className={styles.badgeDiferido} aria-label={`Diferido ${dias} días`}>
                      <Clock size={11} />
                      DIFERIDO — {dias} {dias === 1 ? 'día' : 'días'}
                    </span>
                  )}
                </div>
                <input
                  id="cheque-fecha-pago"
                  type="date"
                  className={styles.inputMono}
                  value={fechaPago}
                  min={fechaEmision}
                  onChange={(e) => setFechaPago(e.target.value)}
                  required
                  disabled={isSaving}
                />
              </div>
            </div>

            {/* Resumen en vivo */}
            {numero && bancoNombreResumen !== '—' && parseFloat(monto) > 0 && (
              <div className={styles.resumenCard}>
                <Info size={15} className={styles.resumenIcon} />
                <p className={styles.resumenText}>
                  Cheque Nº{' '}
                  <strong>{numero}</strong> ·{' '}
                  Banco <strong>{bancoNombreResumen}</strong> ·{' '}
                  <strong>{formatCurrency(parseFloat(monto) || 0, moneda)} {moneda}</strong> ·{' '}
                  vence <strong>{fechaPago}</strong>
                  {esDiferido && (
                    <> · <span className={styles.resumenDiferido}>Diferido {dias}d</span></>
                  )}
                  {tipo === 'tercero' && cuitLibrador && (
                    <> · CUIT <strong>{cuitLibrador}</strong></>
                  )}
                </p>
              </div>
            )}

          </form>
        </div>

        {/* Footer */}
        <footer className={styles.footer}>
          <button
            type="button"
            className={styles.btnCancel}
            onClick={() => onClose(false)}
            disabled={isSaving}
          >
            Cancelar
          </button>
          <button
            type="submit"
            form="form-cheque"
            className={styles.btnSubmit}
            disabled={isSaving}
          >
            {isSaving ? (
              <>
                <Loader2 size={14} className={styles.spin} />
                Emitiendo...
              </>
            ) : (
              <>
                <Send size={14} />
                {tipo === 'tercero' ? 'Recibir en cartera' : 'Emitir cheque'}
              </>
            )}
          </button>
        </footer>

      </div>
    </div>
  );
}
