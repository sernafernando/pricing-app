import { useState, useEffect } from 'react';
import { Check, X } from 'lucide-react';
import api from '../services/api';
import { productosAPI } from '../services/api';
import {
  resolveFilteredItemIds,
  ResolveFilteredIdsError,
  chunkIds,
} from './resolveFilteredItemIds';
import styles from './AplicarMarkupMasivoModal.module.css';

const MAX_ITEMS_POR_REQUEST = 100;
const CONFIRM_THRESHOLD = 50;

export default function AplicarMarkupMasivoModal({
  onClose,
  onSuccess,
  filtrosActivos = {},
  totalProductos = 0,
  showToast,
  puedeEditarCuotas = false,
}) {
  const [aplicarMarkup, setAplicarMarkup] = useState(true);
  const [markupObjetivo, setMarkupObjetivo] = useState('5.0');
  const [recalcularCuotas, setRecalcularCuotas] = useState(true);

  const [aplicarConfig, setAplicarConfig] = useState(false);
  const [recalcularAuto, setRecalcularAuto] = useState('');
  const [markupAdicional, setMarkupAdicional] = useState('');
  const [markupAdicionalGlobal, setMarkupAdicionalGlobal] = useState(false);

  const [aplicando, setAplicando] = useState(false);
  const [progresoLote, setProgresoLote] = useState(null);
  const [resultados, setResultados] = useState(null);
  const [resolvedItemIds, setResolvedItemIds] = useState(null);
  /** Pending apply job awaiting Tesla confirm when count > CONFIRM_THRESHOLD */
  const [confirmacion, setConfirmacion] = useState(null);

  const pricelistId = 4;
  const total =
    resolvedItemIds != null ? resolvedItemIds.length : Number(totalProductos) || 0;

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape' || aplicando) return;
      if (confirmacion) {
        setConfirmacion(null);
        return;
      }
      onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, aplicando, confirmacion]);

  const ejecutarAplicacion = async ({ itemIds, markup, configBodyBase }) => {
    setAplicando(true);
    setResultados(null);
    setProgresoLote(null);

    const lotes = chunkIds(itemIds, MAX_ITEMS_POR_REQUEST);
    const totalLotes = lotes.length;
    const acumulado = { total: 0, ok: 0, errores: 0, resultados: [] };
    let lotesConfig = 0;
    let lotesMarkup = 0;
    let interrumpido = false;

    try {
      if (aplicarConfig) {
        for (let i = 0; i < lotes.length; i++) {
          setProgresoLote({ actual: i + 1, total: totalLotes, accion: 'config' });
          await api.post('/productos/config-cuotas-masivo', {
            item_ids: lotes[i],
            ...configBodyBase,
          });
          lotesConfig += 1;
        }
      }

      if (aplicarMarkup) {
        for (let i = 0; i < lotes.length; i++) {
          setProgresoLote({ actual: i + 1, total: totalLotes, accion: 'markup' });
          const response = await api.post('/precios/aplicar-markup-masivo', {
            markup_objetivo: markup,
            pricelist_id: pricelistId,
            recalcular_cuotas: recalcularCuotas,
            item_ids: lotes[i],
          });
          acumulado.total += response.data.total;
          acumulado.ok += response.data.ok;
          acumulado.errores += response.data.errores;
          acumulado.resultados.push(...response.data.resultados);
          lotesMarkup += 1;
        }
      }
    } catch {
      interrumpido = true;
    } finally {
      setAplicando(false);
      setProgresoLote(null);
      if (aplicarMarkup && acumulado.total > 0) {
        setResultados(acumulado);
      }
    }

    if (interrumpido) {
      const fases = [];
      if (aplicarConfig) fases.push(`config ${lotesConfig}/${totalLotes}`);
      if (aplicarMarkup) fases.push(`markup ${lotesMarkup}/${totalLotes}`);
      showToast(
        `Error al aplicar. Completados ${fases.join(', ')}${
          acumulado.ok ? ` (${acumulado.ok} productos con markup ya actualizado)` : ''
        }`,
        'error',
      );
      if (acumulado.ok > 0 || lotesConfig > 0) onSuccess();
      return;
    }

    if (aplicarMarkup) {
      if (acumulado.errores === 0) {
        showToast(`${acumulado.ok} productos actualizados`);
      } else {
        showToast(`${acumulado.ok} OK / ${acumulado.errores} con error`, 'warning');
      }
      onSuccess();
    } else {
      showToast(
        `Config de cuotas aplicada a ${itemIds.length} producto${itemIds.length !== 1 ? 's' : ''}`,
      );
      onSuccess();
      onClose();
    }
  };

  const handleAplicar = async () => {
    if (total === 0) {
      showToast('No hay productos en el conjunto filtrado', 'error');
      return;
    }
    if (!aplicarMarkup && !aplicarConfig) {
      showToast('Activá al menos una acción', 'error');
      return;
    }

    let markup = null;
    if (aplicarMarkup) {
      markup = parseFloat(markupObjetivo.replace(',', '.'));
      if (isNaN(markup) || markup <= 0) {
        showToast('Ingresá un markup válido mayor a 0', 'error');
        return;
      }
    }

    const configBodyBase = {};
    if (aplicarConfig) {
      if (recalcularAuto !== '') {
        configBodyBase.recalcular_cuotas_auto =
          recalcularAuto === 'null' ? null : recalcularAuto === 'true';
      }
      if (markupAdicionalGlobal) {
        configBodyBase.markup_adicional_cuotas_custom = null;
      } else if (markupAdicional !== '') {
        const adicional = parseFloat(String(markupAdicional).replace(',', '.'));
        if (isNaN(adicional) || adicional < 0 || adicional > 100) {
          showToast('Markup adicional de cuotas debe estar entre 0 y 100', 'error');
          return;
        }
        configBodyBase.markup_adicional_cuotas_custom = adicional;
      }
      if (Object.keys(configBodyBase).length === 0) {
        showToast('Elegí al menos un campo de config de cuotas para aplicar', 'error');
        return;
      }
    }

    setAplicando(true);
    setResultados(null);
    setProgresoLote(null);

    let itemIds;
    try {
      itemIds = await resolveFilteredItemIds({
        listar: productosAPI.listar,
        filtrosActivos,
        totalProductos,
      });
      setResolvedItemIds(itemIds);
    } catch (err) {
      setAplicando(false);
      const msg =
        err instanceof ResolveFilteredIdsError
          ? err.message
          : 'No se pudo resolver el conjunto filtrado de productos';
      showToast(msg, 'error');
      return;
    }

    if (itemIds.length === 0) {
      setAplicando(false);
      showToast('No hay productos en el conjunto filtrado', 'error');
      return;
    }

    const job = { itemIds, markup, configBodyBase };
    if (itemIds.length > CONFIRM_THRESHOLD) {
      setAplicando(false);
      setConfirmacion(job);
      return;
    }

    await ejecutarAplicacion(job);
  };

  const handleConfirmarAplicacion = async () => {
    if (!confirmacion) return;
    const job = confirmacion;
    setConfirmacion(null);
    await ejecutarAplicacion(job);
  };

  const formatPrecio = (v) =>
    v != null ? `$${Number(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}` : '—';

  const tieneConfigParaEnviar =
    recalcularAuto !== '' || markupAdicionalGlobal || markupAdicional !== '';
  const puedeAplicar =
    total > 0 && (aplicarMarkup || aplicarConfig) && (!aplicarConfig || tieneConfigParaEnviar);

  return (
    <div className={styles.overlay}>
      <div className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="acciones-masivas-title">
        <div className={styles.header}>
          <span id="acciones-masivas-title">
            Acciones masivas — {total} producto{total !== 1 ? 's' : ''}
          </span>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            disabled={aplicando}
            aria-label="Cerrar"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className={styles.body}>
          {confirmacion ? (
            <div className={styles.confirmacion}>
              <p className={styles.confirmacionTitulo}>Confirmar acciones masivas</p>
              <p className={styles.descripcion}>
                Vas a aplicar las acciones seleccionadas a{' '}
                <strong>{confirmacion.itemIds.length} productos</strong> del filtro actual.
                Esta operación escribe precios y/o config de cuotas en lote.
              </p>
              <div className={styles.infoBox}>
                Más de {CONFIRM_THRESHOLD} productos requieren confirmación explícita antes de
                escribir.
              </div>
            </div>
          ) : !resultados ? (
            <>
              <section className={styles.seccion}>
                <label className={styles.seccionTitulo}>
                  <input
                    type="checkbox"
                    checked={aplicarMarkup}
                    onChange={(e) => setAplicarMarkup(e.target.checked)}
                    disabled={aplicando}
                  />
                  Aplicar markup ML Clásica
                </label>
                {aplicarMarkup && (
                  <>
                    <p className={styles.descripcion}>
                      Calcula y guarda el precio clásica para el markup objetivo.
                    </p>
                    <div className={styles.field}>
                      <label>Markup objetivo (%):</label>
                      <input
                        type="text"
                        value={markupObjetivo}
                        onChange={(e) => setMarkupObjetivo(e.target.value)}
                        onBlur={(e) => {
                          const v = parseFloat(e.target.value.replace(',', '.'));
                          setMarkupObjetivo(isNaN(v) || v <= 0 ? '5.0' : v.toString());
                        }}
                        onFocus={(e) => e.target.select()}
                        className={styles.input}
                        placeholder="5.0"
                        disabled={aplicando}
                      />
                    </div>
                    <div className={styles.field}>
                      <label className={styles.checkLabel}>
                        <input
                          type="checkbox"
                          checked={recalcularCuotas}
                          onChange={(e) => setRecalcularCuotas(e.target.checked)}
                          disabled={aplicando}
                        />
                        Recalcular precios de cuotas (3 / 6 / 9 / 12)
                      </label>
                    </div>
                  </>
                )}
              </section>

              {puedeEditarCuotas && (
                <section className={styles.seccion}>
                  <label className={styles.seccionTitulo}>
                    <input
                      type="checkbox"
                      checked={aplicarConfig}
                      onChange={(e) => setAplicarConfig(e.target.checked)}
                      disabled={aplicando}
                    />
                    Config de cuotas (engranaje)
                  </label>
                  {aplicarConfig && (
                    <>
                      <p className={styles.descripcion}>
                        Misma config que el engranaje de cada fila, aplicada a todos los
                        productos del filtro actual. Si también aplicás markup, se guarda
                        primero esta config y después se calculan los precios.
                      </p>
                      <div className={styles.field}>
                        <label>Recalcular cuotas automáticamente:</label>
                        <select
                          className={styles.select}
                          value={recalcularAuto}
                          onChange={(e) => setRecalcularAuto(e.target.value)}
                          disabled={aplicando}
                        >
                          <option value="">No cambiar</option>
                          <option value="null">Usar configuración global</option>
                          <option value="true">Siempre recalcular</option>
                          <option value="false">Nunca recalcular</option>
                        </select>
                      </div>
                      <div className={styles.field}>
                        <label>Markup adicional para cuotas Web (%):</label>
                        <input
                          type="text"
                          value={markupAdicional}
                          onChange={(e) => {
                            setMarkupAdicional(e.target.value);
                            if (e.target.value !== '') setMarkupAdicionalGlobal(false);
                          }}
                          onFocus={(e) => e.target.select()}
                          className={styles.input}
                          placeholder="No cambiar"
                          disabled={aplicando || markupAdicionalGlobal}
                        />
                        <label className={styles.checkLabel}>
                          <input
                            type="checkbox"
                            checked={markupAdicionalGlobal}
                            onChange={(e) => {
                              setMarkupAdicionalGlobal(e.target.checked);
                              if (e.target.checked) setMarkupAdicional('');
                            }}
                            disabled={aplicando}
                          />
                          Restablecer al global
                        </label>
                        <span className={styles.help}>
                          Vacío no toca el valor actual. 0 deja las cuotas sin extra sobre clásica.
                        </span>
                      </div>
                    </>
                  )}
                </section>
              )}

              <div className={styles.infoBox}>
                Opera sobre todos los productos del filtro actual (Total {total}).
                {total > MAX_ITEMS_POR_REQUEST && (
                  <>
                    {' '}
                    Hay {total} productos: se enviará en{' '}
                    {Math.ceil(total / MAX_ITEMS_POR_REQUEST)} tandas de hasta{' '}
                    {MAX_ITEMS_POR_REQUEST}.
                  </>
                )}
              </div>
            </>
          ) : (
            <div className={styles.resultados}>
              <div className={styles.resumen}>
                <span className={styles.statOk}>
                  <Check size={16} aria-hidden="true" /> {resultados.ok} OK
                </span>
                {resultados.errores > 0 && (
                  <span className={styles.statError}>
                    <X size={16} aria-hidden="true" /> {resultados.errores} error
                    {resultados.errores !== 1 ? 'es' : ''}
                  </span>
                )}
              </div>
              <div className={styles.tablaWrap}>
                <table className={styles.tabla}>
                  <thead>
                    <tr>
                      <th>Código</th>
                      <th>Descripción</th>
                      <th>Antes</th>
                      <th>Nuevo</th>
                      <th>Markup %</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultados.resultados.map((r) => (
                      <tr key={r.item_id} className={r.ok ? styles.rowOk : styles.rowError}>
                        <td>{r.codigo}</td>
                        <td title={r.descripcion}>
                          {r.descripcion?.length > 35
                            ? `${r.descripcion.slice(0, 35)}…`
                            : r.descripcion}
                        </td>
                        <td>{formatPrecio(r.precio_antes)}</td>
                        <td>{formatPrecio(r.precio_nuevo)}</td>
                        <td>{r.markup_real != null ? `${r.markup_real}%` : '—'}</td>
                        <td>
                          {r.ok ? (
                            <span className={styles.estadoOk}>
                              <Check size={14} aria-hidden="true" /> OK
                            </span>
                          ) : (
                            <span className={styles.estadoError}>
                              <X size={14} aria-hidden="true" /> {r.error}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className={styles.footer}>
          {confirmacion ? (
            <>
              <button
                type="button"
                className={styles.btnSecundario}
                onClick={() => setConfirmacion(null)}
                disabled={aplicando}
              >
                Volver
              </button>
              <button
                type="button"
                className={styles.btnPrimario}
                onClick={handleConfirmarAplicacion}
                disabled={aplicando}
              >
                Confirmar
              </button>
            </>
          ) : !resultados ? (
            <>
              <button
                type="button"
                className={styles.btnSecundario}
                onClick={onClose}
                disabled={aplicando}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnPrimario}
                onClick={handleAplicar}
                disabled={aplicando || !puedeAplicar}
              >
                {aplicando
                  ? progresoLote
                    ? `Aplicando lote ${progresoLote.actual}/${progresoLote.total}...`
                    : 'Aplicando...'
                  : `Aplicar a ${total} producto${total !== 1 ? 's' : ''}`}
              </button>
            </>
          ) : (
            <button type="button" className={styles.btnPrimario} onClick={onClose}>
              Cerrar
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
