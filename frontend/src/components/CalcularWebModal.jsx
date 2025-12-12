import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './CalcularWebModal.module.css';

export default function CalcularWebModal({ onClose, onSuccess, filtrosActivos, showToast }) {
  const [porcentajeConPrecio, setPorcentajeConPrecio] = useState('6.0');
  const [porcentajeSinPrecio, setPorcentajeSinPrecio] = useState('10.0');
  const [calculando, setCalculando] = useState(false);
  const [aplicarFiltros, setAplicarFiltros] = useState(true);

  // Auto-focus en primer input al abrir modal
  useEffect(() => {
    const modal = document.querySelector(`.${styles.modal}`);
    if (modal) {
      const firstInput = modal.querySelector('input');
      if (firstInput) {
        // Pequeño delay para asegurar que el modal esté renderizado
        setTimeout(() => firstInput.focus(), 100);
      }
    }
  }, []);

  // Cerrar modal con Escape y capturar Tab para navegación interna
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !calculando) {
        onClose();
        return;
      }

      // Capturar Tab para mantenerlo dentro del modal
      if (e.key === 'Tab') {
        const modal = document.querySelector(`.${styles.modal}`);
        if (modal) {
          const focusableElements = modal.querySelectorAll(
            'input, button, [tabindex]:not([tabindex="-1"])'
          );
          const firstElement = focusableElements[0];
          const lastElement = focusableElements[focusableElements.length - 1];

          if (e.shiftKey) {
            // Tab + Shift: ir hacia atrás
            if (document.activeElement === firstElement) {
              e.preventDefault();
              lastElement.focus();
            }
          } else {
            // Tab: ir hacia adelante
            if (document.activeElement === lastElement) {
              e.preventDefault();
              firstElement.focus();
            }
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, calculando]);

  const hayFiltros =
    !!filtrosActivos?.search ||
    filtrosActivos?.con_stock !== null ||
    filtrosActivos?.con_precio !== null ||
    (filtrosActivos?.marcas?.length > 0) ||
    (filtrosActivos?.subcategorias?.length > 0) ||
    filtrosActivos?.filtroRebate !== null ||
    filtrosActivos?.filtroOferta !== null ||
    filtrosActivos?.filtroWebTransf !== null ||
    filtrosActivos?.filtroTiendaNube !== null ||
    filtrosActivos?.filtroMarkupClasica !== null ||
    filtrosActivos?.filtroMarkupRebate !== null ||
    filtrosActivos?.filtroMarkupOferta !== null ||
    filtrosActivos?.filtroMarkupWebTransf !== null ||
    filtrosActivos?.filtroOutOfCards !== null ||
    (filtrosActivos?.coloresSeleccionados?.length > 0) ||
    (filtrosActivos?.pmsSeleccionados?.length > 0) ||
    (filtrosActivos?.audit_usuarios?.length > 0) ||
    (filtrosActivos?.audit_tipos_accion?.length > 0) ||
    !!filtrosActivos?.audit_fecha_desde ||
    !!filtrosActivos?.audit_fecha_hasta;

  const FiltrosActivosDisplay = () => (
    <div className={styles.filtrosActivos}>
      {filtrosActivos.search && <div>• Búsqueda: "{filtrosActivos.search}"</div>}
      {filtrosActivos.con_stock === true && <div>• Con stock</div>}
      {filtrosActivos.con_stock === false && <div>• Sin stock</div>}
      {filtrosActivos.con_precio === true && <div>• Con precio</div>}
      {filtrosActivos.con_precio === false && <div>• Sin precio</div>}
      {filtrosActivos.marcas?.length > 0 && <div>• {filtrosActivos.marcas.length} marca(s)</div>}
      {filtrosActivos.subcategorias?.length > 0 && <div>• {filtrosActivos.subcategorias.length} subcategoría(s)</div>}
      {filtrosActivos.filtroRebate === 'con_rebate' && <div>• Con Rebate</div>}
      {filtrosActivos.filtroRebate === 'sin_rebate' && <div>• Sin Rebate</div>}
      {filtrosActivos.filtroOferta === 'con_oferta' && <div>• Con Oferta</div>}
      {filtrosActivos.filtroOferta === 'sin_oferta' && <div>• Sin Oferta</div>}
      {filtrosActivos.filtroWebTransf === 'con_web_transf' && <div>• Con Web Transferencia</div>}
      {filtrosActivos.filtroWebTransf === 'sin_web_transf' && <div>• Sin Web Transferencia</div>}
      {filtrosActivos.filtroTiendaNube === 'con_descuento' && <div>• Tienda Nube: Con Descuento</div>}
      {filtrosActivos.filtroTiendaNube === 'sin_descuento' && <div>• Tienda Nube: Sin Descuento</div>}
      {filtrosActivos.filtroTiendaNube === 'no_publicado' && <div>• Tienda Nube: No Publicado</div>}
      {filtrosActivos.filtroOutOfCards === 'con_out_of_cards' && <div>• Con Out of Cards</div>}
      {filtrosActivos.filtroOutOfCards === 'sin_out_of_cards' && <div>• Sin Out of Cards</div>}
      {filtrosActivos.filtroMarkupClasica === 'positivo' && <div>• Markup Clásica: Positivo</div>}
      {filtrosActivos.filtroMarkupClasica === 'negativo' && <div>• Markup Clásica: Negativo</div>}
      {filtrosActivos.filtroMarkupRebate === 'positivo' && <div>• Markup Rebate: Positivo</div>}
      {filtrosActivos.filtroMarkupRebate === 'negativo' && <div>• Markup Rebate: Negativo</div>}
      {filtrosActivos.filtroMarkupOferta === 'positivo' && <div>• Markup Oferta: Positivo</div>}
      {filtrosActivos.filtroMarkupOferta === 'negativo' && <div>• Markup Oferta: Negativo</div>}
      {filtrosActivos.filtroMarkupWebTransf === 'positivo' && <div>• Markup Web Transf: Positivo</div>}
      {filtrosActivos.filtroMarkupWebTransf === 'negativo' && <div>• Markup Web Transf: Negativo</div>}
      {filtrosActivos.coloresSeleccionados?.length > 0 && <div>• {filtrosActivos.coloresSeleccionados.length} color(es) seleccionado(s)</div>}
      {filtrosActivos.pmsSeleccionados?.length > 0 && <div>• {filtrosActivos.pmsSeleccionados.length} PM(s) seleccionado(s)</div>}
      {filtrosActivos.audit_usuarios?.length > 0 && <div>• {filtrosActivos.audit_usuarios.length} usuario(s) auditoría</div>}
      {filtrosActivos.audit_tipos_accion?.length > 0 && <div>• {filtrosActivos.audit_tipos_accion.length} tipo(s) de acción</div>}
      {filtrosActivos.audit_fecha_desde && <div>• Auditoría desde: {filtrosActivos.audit_fecha_desde}</div>}
      {filtrosActivos.audit_fecha_hasta && <div>• Auditoría hasta: {filtrosActivos.audit_fecha_hasta}</div>}
    </div>
  );

  const calcularMasivo = async () => {
    const mensaje = aplicarFiltros
      ? '¿Confirmar cálculo de precios web transferencia para los productos FILTRADOS?'
      : '¿Confirmar cálculo masivo de precios web transferencia para TODOS los productos?';

    if (!confirm(mensaje)) return;

    setCalculando(true);
    try {
      const token = localStorage.getItem('token');

      const body = {
        porcentaje_con_precio: parseFloat(porcentajeConPrecio.toString().replace(',', '.')) || 0,
        porcentaje_sin_precio: parseFloat(porcentajeSinPrecio.toString().replace(',', '.')) || 0
      };

      if (aplicarFiltros) {
        body.filtros = {
          search: filtrosActivos.search || null,
          con_stock: filtrosActivos.con_stock || null,
          con_precio: filtrosActivos.con_precio || null,
          marcas: filtrosActivos.marcas?.length > 0 ? filtrosActivos.marcas.join(',') : null,
          subcategorias: filtrosActivos.subcategorias?.length > 0 ? filtrosActivos.subcategorias.join(',') : null
        };

        if (filtrosActivos.filtroRebate === 'con_rebate') body.filtros.con_rebate = true;
        if (filtrosActivos.filtroRebate === 'sin_rebate') body.filtros.con_rebate = false;
        if (filtrosActivos.filtroOferta === 'con_oferta') body.filtros.con_oferta = true;
        if (filtrosActivos.filtroOferta === 'sin_oferta') body.filtros.con_oferta = false;
        if (filtrosActivos.filtroWebTransf === 'con_web_transf') body.filtros.con_web_transf = true;
        if (filtrosActivos.filtroWebTransf === 'sin_web_transf') body.filtros.con_web_transf = false;
        if (filtrosActivos.filtroTiendaNube === 'con_descuento') body.filtros.tiendanube_con_descuento = true;
        if (filtrosActivos.filtroTiendaNube === 'sin_descuento') body.filtros.tiendanube_sin_descuento = true;
        if (filtrosActivos.filtroTiendaNube === 'no_publicado') body.filtros.tiendanube_no_publicado = true;
        if (filtrosActivos.filtroMarkupClasica === 'positivo') body.filtros.markup_clasica_positivo = true;
        if (filtrosActivos.filtroMarkupClasica === 'negativo') body.filtros.markup_clasica_positivo = false;
        if (filtrosActivos.filtroMarkupRebate === 'positivo') body.filtros.markup_rebate_positivo = true;
        if (filtrosActivos.filtroMarkupRebate === 'negativo') body.filtros.markup_rebate_positivo = false;
        if (filtrosActivos.filtroMarkupOferta === 'positivo') body.filtros.markup_oferta_positivo = true;
        if (filtrosActivos.filtroMarkupOferta === 'negativo') body.filtros.markup_oferta_positivo = false;
        if (filtrosActivos.filtroMarkupWebTransf === 'positivo') body.filtros.markup_web_transf_positivo = true;
        if (filtrosActivos.filtroMarkupWebTransf === 'negativo') body.filtros.markup_web_transf_positivo = false;
        if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') body.filtros.out_of_cards = true;
        if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') body.filtros.out_of_cards = false;
        if (filtrosActivos.coloresSeleccionados?.length > 0) body.filtros.colores = filtrosActivos.coloresSeleccionados.join(',');
        if (filtrosActivos.pmsSeleccionados?.length > 0) body.filtros.pms = filtrosActivos.pmsSeleccionados.join(',');
        if (filtrosActivos.audit_usuarios?.length > 0) body.filtros.audit_usuarios = filtrosActivos.audit_usuarios.join(',');
        if (filtrosActivos.audit_tipos_accion?.length > 0) body.filtros.audit_tipos_accion = filtrosActivos.audit_tipos_accion.join(',');
        if (filtrosActivos.audit_fecha_desde) body.filtros.audit_fecha_desde = filtrosActivos.audit_fecha_desde;
        if (filtrosActivos.audit_fecha_hasta) body.filtros.audit_fecha_hasta = filtrosActivos.audit_fecha_hasta;
        if (filtrosActivos.filtroMLA === 'con_mla') body.filtros.con_mla = true;
        if (filtrosActivos.filtroMLA === 'sin_mla') body.filtros.con_mla = false;
        if (filtrosActivos.filtroEstadoMLA === 'activa') body.filtros.estado_mla = 'activa';
        if (filtrosActivos.filtroEstadoMLA === 'pausada') body.filtros.estado_mla = 'pausada';
        if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') body.filtros.nuevos_ultimos_7_dias = true;
      }

      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/productos/calcular-web-masivo',
        body,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      showToast(`✅ Precios calculados: ${response.data.procesados} productos`);
      onSuccess();
      onClose();
    } catch (error) {
      console.error('Error:', error);
      showToast('❌ Error al calcular precios masivos', 'error');
    } finally {
      setCalculando(false);
    }
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <h2 className={styles.title}>🧮 Calcular Precios Web Transferencia</h2>
          <button onClick={onClose} className={styles.closeButton}>×</button>
        </div>

        <div className={styles.content}>
          <p className={styles.description}>
            Calcula automáticamente los precios de Web Transferencia aplicando los porcentajes configurados sobre el precio clásica.
          </p>

          {hayFiltros && (
            <div className={styles.filterCheckbox}>
              <label>
                <input
                  type="checkbox"
                  checked={aplicarFiltros}
                  onChange={(e) => setAplicarFiltros(e.target.checked)}
                />
                Calcular solo productos filtrados
              </label>
              {aplicarFiltros && <FiltrosActivosDisplay />}
            </div>
          )}

          <div style={{ display: 'grid', gap: '16px', marginBottom: '24px' }}>
            <div>
              <label className={styles.label}>
                % para productos CON precio web transferencia:
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={porcentajeConPrecio}
                onChange={(e) => {
                  // Aceptar cualquier entrada, dejar que el usuario escriba libremente
                  setPorcentajeConPrecio(e.target.value);
                }}
                onBlur={(e) => {
                  // Al salir del campo, validar que sea un número válido
                  const valor = e.target.value.replace(',', '.');
                  const numero = parseFloat(valor);
                  if (!isNaN(numero)) {
                    setPorcentajeConPrecio(numero.toString());
                  } else {
                    setPorcentajeConPrecio('0');
                  }
                }}
                onFocus={(e) => e.target.select()}
                className={styles.input}
                placeholder="0.0"
              />
              <small style={{ display: 'block', marginTop: '4px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                Se suma este % al precio clásica
              </small>
            </div>

            <div>
              <label className={styles.label}>
                % para productos SIN precio web transferencia:
              </label>
              <input
                type="text"
                inputMode="decimal"
                value={porcentajeSinPrecio}
                onChange={(e) => {
                  // Aceptar cualquier entrada, dejar que el usuario escriba libremente
                  setPorcentajeSinPrecio(e.target.value);
                }}
                onBlur={(e) => {
                  // Al salir del campo, validar que sea un número válido
                  const valor = e.target.value.replace(',', '.');
                  const numero = parseFloat(valor);
                  if (!isNaN(numero)) {
                    setPorcentajeSinPrecio(numero.toString());
                  } else {
                    setPorcentajeSinPrecio('0');
                  }
                }}
                onFocus={(e) => e.target.select()}
                className={styles.input}
                placeholder="0.0"
              />
              <small style={{ display: 'block', marginTop: '4px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                Se suma este % al precio clásica (primera vez)
              </small>
            </div>
          </div>

          <div className={styles.buttonGroup}>
            <button
              onClick={onClose}
              disabled={calculando}
              className={`${styles.button} ${styles.buttonSecondary}`}
            >
              Cancelar
            </button>
            <button
              onClick={calcularMasivo}
              disabled={calculando}
              className={`${styles.button} ${styles.buttonPrimary}`}
            >
              {calculando ? '⏳ Calculando...' : '🧮 Calcular Precios'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
