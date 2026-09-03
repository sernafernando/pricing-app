import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './AplicarMarkupMasivoModal.module.css';

export default function AplicarMarkupMasivoModal({
  onClose,
  onSuccess,
  productos,
  showToast,
  puedeEditarCuotas = false,
}) {
  const [aplicarMarkup, setAplicarMarkup] = useState(true);
  const [markupObjetivo, setMarkupObjetivo] = useState('5.0');
  const [recalcularCuotas, setRecalcularCuotas] = useState(true);

  const [aplicarConfig, setAplicarConfig] = useState(false);
  const [recalcularAuto, setRecalcularAuto] = useState('null');
  const [markupAdicional, setMarkupAdicional] = useState('');

  const [aplicando, setAplicando] = useState(false);
  const [resultados, setResultados] = useState(null);

  const pricelistId = 4;
  const total = productos?.length ?? 0;
  const itemIds = (productos || []).map((p) => p.item_id);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !aplicando) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, aplicando]);

  const handleAplicar = async () => {
    if (total === 0) {
      showToast('No hay productos en la vista actual', 'error');
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

    setAplicando(true);
    setResultados(null);

    try {
      if (aplicarConfig) {
        const adicional = markupAdicional === '' ? null : parseFloat(String(markupAdicional).replace(',', '.'));
        if (adicional != null && (isNaN(adicional) || adicional < 0 || adicional > 100)) {
          showToast('Markup adicional de cuotas debe estar entre 0 y 100', 'error');
          setAplicando(false);
          return;
        }
        await api.post('/productos/config-cuotas-masivo', {
          item_ids: itemIds,
          recalcular_cuotas_auto:
            recalcularAuto === 'null' ? null : recalcularAuto === 'true',
          markup_adicional_cuotas_custom: adicional,
        });
      }

      if (aplicarMarkup) {
        const response = await api.post('/precios/aplicar-markup-masivo', {
          markup_objetivo: markup,
          pricelist_id: pricelistId,
          recalcular_cuotas: recalcularCuotas,
          item_ids: itemIds,
        });
        setResultados(response.data);
        if (response.data.errores === 0) {
          showToast(`✅ ${response.data.ok} productos actualizados`);
        } else {
          showToast(`⚠️ ${response.data.ok} OK / ${response.data.errores} con error`, 'warning');
        }
      } else {
        showToast(`✅ Config de cuotas aplicada a ${total} producto${total !== 1 ? 's' : ''}`);
        onSuccess();
        onClose();
        return;
      }

      onSuccess();
    } catch (error) {
      console.error('Error acciones masivas:', error);
      showToast('❌ Error al aplicar acciones masivas', 'error');
    } finally {
      setAplicando(false);
    }
  };

  const formatPrecio = (v) =>
    v != null ? `$${Number(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}` : '—';

  const puedeAplicar = total > 0 && (aplicarMarkup || aplicarConfig);

  return (
    <div
      className={styles.overlay}
      onClick={(e) => e.target === e.currentTarget && !aplicando && onClose()}
    >
      <div className={styles.modal}>
        <div className={styles.header}>
          <span>Acciones masivas — {total} producto{total !== 1 ? 's' : ''} visible{total !== 1 ? 's' : ''}</span>
          <button className={styles.closeBtn} onClick={onClose} disabled={aplicando}>
            ×
          </button>
        </div>

        <div className={styles.body}>
          {!resultados ? (
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
                        Misma config que el engranaje de cada fila, aplicada a todos los visibles.
                        Si también aplicás markup, se guarda primero esta config y después se calculan los precios.
                      </p>
                      <div className={styles.field}>
                        <label>Recalcular cuotas automáticamente:</label>
                        <select
                          className={styles.select}
                          value={recalcularAuto}
                          onChange={(e) => setRecalcularAuto(e.target.value)}
                          disabled={aplicando}
                        >
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
                          onChange={(e) => setMarkupAdicional(e.target.value)}
                          onFocus={(e) => e.target.select()}
                          className={styles.input}
                          placeholder="Vacío = global"
                          disabled={aplicando}
                        />
                        <span className={styles.help}>
                          Vacío usa el global. 0 deja las cuotas sin extra sobre clásica.
                        </span>
                      </div>
                    </>
                  )}
                </section>
              )}

              <div className={styles.infoBox}>
                Opera solo sobre los productos visibles en la grilla (página actual y filtros).
              </div>
            </>
          ) : (
            <div className={styles.resultados}>
              <div className={styles.resumen}>
                <span className={styles.statOk}>✅ {resultados.ok} OK</span>
                {resultados.errores > 0 && (
                  <span className={styles.statError}>
                    ❌ {resultados.errores} error{resultados.errores !== 1 ? 'es' : ''}
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
                        <td>{r.ok ? '✅' : `❌ ${r.error}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <div className={styles.footer}>
          {!resultados ? (
            <>
              <button className={styles.btnSecundario} onClick={onClose} disabled={aplicando}>
                Cancelar
              </button>
              <button
                className={styles.btnPrimario}
                onClick={handleAplicar}
                disabled={aplicando || !puedeAplicar}
              >
                {aplicando ? 'Aplicando...' : `Aplicar a ${total} producto${total !== 1 ? 's' : ''}`}
              </button>
            </>
          ) : (
            <button className={styles.btnPrimario} onClick={onClose}>
              Cerrar
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
