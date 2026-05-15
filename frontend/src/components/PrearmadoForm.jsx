import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { X, Check, AlertTriangle } from 'lucide-react';
import api from '../services/api';
import SearchInput from './SearchInput';
import styles from '../pages/Prearmado.module.css';

const WINDOWS_LABEL = {
  home: 'Windows 11 Home',
  pro: 'Windows 11 Pro',
};

export default function PrearmadoForm({ onClose, onSaved }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [combosResults, setCombosResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [combo, setCombo] = useState(null);
  const [componentes, setComponentes] = useState([]);
  const [incluyeWindows, setIncluyeWindows] = useState(null);
  const [serialInputs, setSerialInputs] = useState({});
  const [validaciones, setValidaciones] = useState({});
  const [notas, setNotas] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // Refs a cada input de serial (key → DOM node) para focus/select on scan
  const serialInputRefs = useRef({});

  // Orden de keys de inputs serializables — para saber a cuál saltar al validar OK
  const serialInputKeys = useMemo(() => {
    const keys = [];
    componentes.forEach((c) => {
      if (!c.requiere_serie) return;
      for (let i = 0; i < (c.cantidad_esperada || 1); i++) {
        keys.push(`${c.item_id}_${i}`);
      }
    });
    return keys;
  }, [componentes]);

  useEffect(() => {
    if (!searchTerm || searchTerm.length < 2 || combo) {
      setCombosResults([]);
      return;
    }
    const handle = setTimeout(async () => {
      setSearching(true);
      try {
        const resp = await api.get('/prearmado/combos/search', {
          params: { q: searchTerm, limit: 20 },
        });
        setCombosResults(resp.data || []);
      } catch {
        setCombosResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(handle);
  }, [searchTerm, combo]);

  const seleccionarCombo = useCallback(async (c) => {
    setError(null);
    setCombo(c);
    setSearchTerm('');
    setCombosResults([]);
    try {
      const resp = await api.get(`/prearmado/componentes/${c.item_id}`);
      setComponentes(resp.data.componentes || []);
      setIncluyeWindows(resp.data.incluye_windows || null);
      setSerialInputs({});
      setValidaciones({});
    } catch (err) {
      setError(err.response?.data?.detail || 'Error cargando componentes');
    }
  }, []);

  const validarSerial = useCallback(async (key, serial, itemId) => {
    if (!serial || !serial.trim()) {
      setValidaciones((v) => ({ ...v, [key]: null }));
      return null;
    }
    try {
      const resp = await api.post('/prearmado/validar-serial', {
        serial: serial.trim(),
        item_id_esperado: itemId,
      });
      setValidaciones((v) => ({ ...v, [key]: resp.data }));
      return resp.data;
    } catch {
      const err = { valid: false, motivo: 'NetworkError' };
      setValidaciones((v) => ({ ...v, [key]: err }));
      return err;
    }
  }, []);

  // Enter de la pistola: si validó OK, salta al siguiente input.
  // Si falló (rojo), selecciona todo el texto para que el próximo pistoletazo lo sobrescriba.
  const onSerialKeyDown = useCallback(
    async (e, key, itemId) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const serial = e.currentTarget.value;
      const result = await validarSerial(key, serial, itemId);
      if (result?.valid) {
        const idx = serialInputKeys.indexOf(key);
        const nextKey = serialInputKeys[idx + 1];
        const nextEl = nextKey ? serialInputRefs.current[nextKey] : null;
        if (nextEl) {
          nextEl.focus();
          nextEl.select();
        } else {
          e.currentTarget.blur();
        }
      } else {
        e.currentTarget.select();
      }
    },
    [validarSerial, serialInputKeys],
  );

  const setSerialInput = (key, value) => {
    setSerialInputs((s) => ({ ...s, [key]: { ...(s[key] || {}), serial: value } }));
  };

  const setForceFlag = (key, force) => {
    setSerialInputs((s) => ({ ...s, [key]: { ...(s[key] || {}), force } }));
  };

  const guardar = async () => {
    if (!combo) return;
    setSaving(true);
    setError(null);
    try {
      const crearResp = await api.post('/prearmado', {
        combo_item_id: combo.item_id,
        notas: notas || null,
      });
      const prearmadoId = crearResp.data.id;

      const items = [];
      componentes.forEach((c) => {
        for (let i = 0; i < (c.cantidad_esperada || 1); i++) {
          const key = `${c.item_id}_${i}`;
          if (!c.requiere_serie) {
            items.push({
              componente_item_id: c.item_id,
              componente_item_code: c.item_code,
              componente_item_desc: c.item_desc,
              cantidad_esperada: 1,
              requiere_serie: false,
              origen: c.origen,
              sufijo: c.sufijo,
            });
            break; // un row solo para no-serializables
          }
          const input = serialInputs[key];
          if (!input || !input.serial || !input.serial.trim()) continue;
          items.push({
            componente_item_id: c.item_id,
            componente_item_code: c.item_code,
            componente_item_desc: c.item_desc,
            serial: input.serial.trim(),
            cantidad_esperada: 1,
            requiere_serie: true,
            origen: c.origen,
            sufijo: c.sufijo,
            force: !!input.force,
          });
        }
      });

      if (items.length > 0) {
        await api.post(`/prearmado/${prearmadoId}/seriales`, { items });
      }

      onSaved?.();
      onClose?.();
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'object' && detail?.errores) {
        setError(
          `Seriales inválidos en ${detail.errores.length} componente(s). Marcá "forzar" para guardar igual.`,
        );
      } else {
        setError(detail || err.message || 'Error guardando el prearmado');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.modalBackdrop} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h2 className={styles.modalTitle}>Nuevo prearmado</h2>
          <button
            type="button"
            className={styles.modalCloseBtn}
            onClick={onClose}
            aria-label="Cerrar"
          >
            <X size={18} />
          </button>
        </div>

        <div className={styles.modalBody}>
          {!combo ? (
            <div className={styles.comboSelector}>
              <label className={styles.comboSelectorLabel}>Buscar combo</label>
              <SearchInput
                value={searchTerm}
                onChange={setSearchTerm}
                placeholder="Código o descripción del combo..."
                size="sm"
              />
              {searching && <p className={styles.smallMuted}>Buscando...</p>}
              {combosResults.length > 0 && (
                <div className={styles.combosResultsList}>
                  {combosResults.map((r) => (
                    <button
                      key={r.item_id}
                      type="button"
                      onClick={() => seleccionarCombo(r)}
                      className={styles.comboResultBtn}
                    >
                      <span className={styles.comboResultCode}>{r.item_code}</span>
                      <span className={styles.comboResultDesc}>{r.item_desc}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <>
              <div className={styles.comboMeta}>
                <div className={styles.comboMetaInfo}>
                  <div className={styles.comboMetaCode}>{combo.item_code}</div>
                  <div className={styles.smallMuted}>{combo.item_desc}</div>
                </div>
                {incluyeWindows && (
                  <span className={styles.windowsBadge}>
                    Incluye {WINDOWS_LABEL[incluyeWindows]}
                  </span>
                )}
                <button
                  type="button"
                  className={styles.actionBtn}
                  onClick={() => {
                    setCombo(null);
                    setComponentes([]);
                    setSerialInputs({});
                    setValidaciones({});
                    setIncluyeWindows(null);
                  }}
                >
                  Cambiar
                </button>
              </div>

              {componentes.length === 0 ? (
                <div className={styles.muted}>Sin componentes en la BOM.</div>
              ) : (
                componentes.map((c) =>
                  Array.from({ length: c.requiere_serie ? c.cantidad_esperada : 1 }).map(
                    (_, idx) => {
                      const key = `${c.item_id}_${idx}`;
                      const validation = validaciones[key];
                      const input = serialInputs[key];
                      return (
                        <div key={key} className={styles.componenteRow}>
                          <div className={styles.componenteInfo}>
                            <span className={styles.componenteCode}>{c.item_code}</span>
                            <span className={styles.componenteDesc}>{c.item_desc}</span>
                            {c.cantidad_esperada > 1 && c.requiere_serie && (
                              <span className={styles.cantidadIndicador}>
                                ({idx + 1}/{c.cantidad_esperada})
                              </span>
                            )}
                          </div>
                          {c.requiere_serie ? (
                            <div className={styles.serialInputWrap}>
                              <div className={styles.serialInputRow}>
                                <input
                                  ref={(el) => {
                                    if (el) serialInputRefs.current[key] = el;
                                    else delete serialInputRefs.current[key];
                                  }}
                                  type="text"
                                  className={styles.componenteSerialInput}
                                  placeholder="N° de serie"
                                  value={input?.serial || ''}
                                  onChange={(e) => setSerialInput(key, e.target.value)}
                                  onBlur={(e) => validarSerial(key, e.target.value, c.item_id)}
                                  onKeyDown={(e) => onSerialKeyDown(e, key, c.item_id)}
                                />
                                {validation?.valid && (
                                  <Check size={16} className={styles.validacionOk} aria-label="Válido" />
                                )}
                                {validation && !validation.valid && (
                                  <AlertTriangle
                                    size={16}
                                    className={styles.validacionWarn}
                                    aria-label={validation.motivo}
                                  />
                                )}
                              </div>
                              {validation && !validation.valid && (
                                <label className={styles.forceCheckbox}>
                                  <input
                                    type="checkbox"
                                    checked={!!input?.force}
                                    onChange={(e) => setForceFlag(key, e.target.checked)}
                                  />
                                  Forzar guardado (
                                  {validation.motivo === 'SerialNotFound'
                                    ? 'serial no encontrado en ERP'
                                    : validation.motivo === 'ItemMismatch'
                                      ? `pertenece a item ${validation.item_code_real || validation.item_id_real}`
                                      : validation.motivo === 'AlreadyInSaleOrder'
                                        ? `ya asignado al pedido SOH ${validation.usado_en_soh_id}`
                                        : validation.motivo === 'AlreadyInvoiced'
                                          ? `ya facturado (pedido SOH ${validation.usado_en_factura_soh_id})`
                                          : 'inválido'}
                                  )
                                </label>
                              )}
                            </div>
                          ) : (
                            <span className={styles.noRequiereSerie}>No requiere serie</span>
                          )}
                        </div>
                      );
                    },
                  ),
                )
              )}

              <div className={styles.notasField}>
                <label className={styles.comboSelectorLabel}>Notas (opcional)</label>
                <textarea
                  value={notas}
                  onChange={(e) => setNotas(e.target.value)}
                  rows={2}
                  className={styles.notasTextarea}
                />
              </div>
            </>
          )}

          {error && <div className={styles.errorBanner} role="alert">{error}</div>}
        </div>

        <div className={styles.modalFooter}>
          <button type="button" className={styles.actionBtn} onClick={onClose} disabled={saving}>
            Cancelar
          </button>
          <button
            type="button"
            className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
            onClick={guardar}
            disabled={!combo || saving}
          >
            {saving ? 'Guardando...' : 'Guardar prearmado'}
          </button>
        </div>
      </div>
    </div>
  );
}
