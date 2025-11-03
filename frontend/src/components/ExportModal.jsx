import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './ExportModal.module.css';

export default function ExportModal({ onClose, filtrosActivos }) {
  const [tab, setTab] = useState('rebate');
  const [exportando, setExportando] = useState(false);
  const [aplicarFiltros, setAplicarFiltros] = useState(true);
  const [porcentajeClasica, setPorcentajeClasica] = useState('0');

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
      if (e.key === 'Escape' && !exportando) {
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
  }, [onClose, exportando]);

  const hayFiltros =
    !!filtrosActivos?.search ||
    filtrosActivos?.con_stock !== null ||
    filtrosActivos?.con_precio !== null ||
    (filtrosActivos?.marcas?.length > 0) ||
    (filtrosActivos?.subcategorias?.length > 0) ||
    filtrosActivos?.filtroRebate !== null ||
    filtrosActivos?.filtroOferta !== null ||
    filtrosActivos?.filtroWebTransf !== null ||
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

  const agregarFiltrosAvanzados = (params) => {
    if (filtrosActivos.filtroRebate === 'con_rebate') params.con_rebate = true;
    if (filtrosActivos.filtroRebate === 'sin_rebate') params.con_rebate = false;
    if (filtrosActivos.filtroOferta === 'con_oferta') params.con_oferta = true;
    if (filtrosActivos.filtroOferta === 'sin_oferta') params.con_oferta = false;
    if (filtrosActivos.filtroWebTransf === 'con_web_transf') params.con_web_transf = true;
    if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params.con_web_transf = false;
    if (filtrosActivos.filtroMarkupClasica === 'positivo') params.markup_clasica_positivo = true;
    if (filtrosActivos.filtroMarkupClasica === 'negativo') params.markup_clasica_positivo = false;
    if (filtrosActivos.filtroMarkupRebate === 'positivo') params.markup_rebate_positivo = true;
    if (filtrosActivos.filtroMarkupRebate === 'negativo') params.markup_rebate_positivo = false;
    if (filtrosActivos.filtroMarkupOferta === 'positivo') params.markup_oferta_positivo = true;
    if (filtrosActivos.filtroMarkupOferta === 'negativo') params.markup_oferta_positivo = false;
    if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params.markup_web_transf_positivo = true;
    if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params.markup_web_transf_positivo = false;
    if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params.out_of_cards = true;
    if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params.out_of_cards = false;
    if (filtrosActivos.coloresSeleccionados?.length > 0) params.colores = filtrosActivos.coloresSeleccionados.join(',');
    if (filtrosActivos.pmsSeleccionados?.length > 0) params.pms = filtrosActivos.pmsSeleccionados.join(',');
    if (filtrosActivos.audit_usuarios?.length > 0) params.audit_usuarios = filtrosActivos.audit_usuarios.join(',');
    if (filtrosActivos.audit_tipos_accion?.length > 0) params.audit_tipos_accion = filtrosActivos.audit_tipos_accion.join(',');
    if (filtrosActivos.audit_fecha_desde) params.audit_fecha_desde = filtrosActivos.audit_fecha_desde;
    if (filtrosActivos.audit_fecha_hasta) params.audit_fecha_hasta = filtrosActivos.audit_fecha_hasta;
    return params;
  };

  const FiltrosActivosDisplay = () => (
    <div className={styles.filtrosActivos}>
      {filtrosActivos?.search && <div>• Búsqueda: "{filtrosActivos.search}"</div>}
      {filtrosActivos?.con_stock === true && <div>• Con stock</div>}
      {filtrosActivos?.con_stock === false && <div>• Sin stock</div>}
      {filtrosActivos?.con_precio === true && <div>• Con precio</div>}
      {filtrosActivos?.con_precio === false && <div>• Sin precio</div>}
      {filtrosActivos?.marcas?.length > 0 && <div>• {filtrosActivos.marcas.length} marca(s)</div>}
      {filtrosActivos?.subcategorias?.length > 0 && <div>• {filtrosActivos.subcategorias.length} subcategoría(s)</div>}
      {filtrosActivos?.filtroRebate === 'con_rebate' && <div>• Con Rebate</div>}
      {filtrosActivos?.filtroRebate === 'sin_rebate' && <div>• Sin Rebate</div>}
      {filtrosActivos?.filtroOferta === 'con_oferta' && <div>• Con Oferta</div>}
      {filtrosActivos?.filtroOferta === 'sin_oferta' && <div>• Sin Oferta</div>}
      {filtrosActivos?.filtroWebTransf === 'con_web_transf' && <div>• Con Web Transferencia</div>}
      {filtrosActivos?.filtroWebTransf === 'sin_web_transf' && <div>• Sin Web Transferencia</div>}
      {filtrosActivos?.filtroOutOfCards === 'con_out_of_cards' && <div>• Con Out of Cards</div>}
      {filtrosActivos?.filtroOutOfCards === 'sin_out_of_cards' && <div>• Sin Out of Cards</div>}
      {filtrosActivos?.filtroMarkupClasica === 'positivo' && <div>• Markup Clásica: Positivo</div>}
      {filtrosActivos?.filtroMarkupClasica === 'negativo' && <div>• Markup Clásica: Negativo</div>}
      {filtrosActivos?.filtroMarkupRebate === 'positivo' && <div>• Markup Rebate: Positivo</div>}
      {filtrosActivos?.filtroMarkupRebate === 'negativo' && <div>• Markup Rebate: Negativo</div>}
      {filtrosActivos?.filtroMarkupOferta === 'positivo' && <div>• Markup Oferta: Positivo</div>}
      {filtrosActivos?.filtroMarkupOferta === 'negativo' && <div>• Markup Oferta: Negativo</div>}
      {filtrosActivos?.filtroMarkupWebTransf === 'positivo' && <div>• Markup Web Transf: Positivo</div>}
      {filtrosActivos?.filtroMarkupWebTransf === 'negativo' && <div>• Markup Web Transf: Negativo</div>}
      {filtrosActivos?.audit_usuarios?.length > 0 && <div>• {filtrosActivos.audit_usuarios.length} usuario(s) auditoría</div>}
      {filtrosActivos?.audit_tipos_accion?.length > 0 && <div>• {filtrosActivos.audit_tipos_accion.length} tipo(s) de acción</div>}
      {filtrosActivos?.audit_fecha_desde && <div>• Auditoría desde: {filtrosActivos.audit_fecha_desde}</div>}
      {filtrosActivos?.audit_fecha_hasta && <div>• Auditoría hasta: {filtrosActivos.audit_fecha_hasta}</div>}
      {filtrosActivos?.coloresSeleccionados?.length > 0 && <div>• {filtrosActivos.coloresSeleccionados.length} color(es) seleccionado(s)</div>}
      {filtrosActivos?.pmsSeleccionados?.length > 0 && <div>• {filtrosActivos.pmsSeleccionados.length} PM(s) seleccionado(s)</div>}
    </div>
  );

  const [fechaDesde, setFechaDesde] = useState(() => {
    const hoy = new Date();
    return hoy.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });
  const [fechaHasta, setFechaHasta] = useState(() => {
    const hoy = new Date();
    const ultimoDia = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0);
    return ultimoDia.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });

  const [porcentajeWebTransf, setPorcentajeWebTransf] = useState('0');

  const convertirFechaParaAPI = (fechaDD_MM_YYYY) => {
    const [d, m, y] = fechaDD_MM_YYYY.split('/');
    return `${y}-${m}-${d}`;
  };

  const exportarRebate = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      const body = {
        fecha_desde: convertirFechaParaAPI(fechaDesde),
        fecha_hasta: convertirFechaParaAPI(fechaHasta)
      };

      if (aplicarFiltros) {
        body.filtros = {
          search: filtrosActivos.search || null,
          con_stock: filtrosActivos.con_stock,
          con_precio: filtrosActivos.con_precio,
          marcas: filtrosActivos.marcas?.length > 0 ? filtrosActivos.marcas.join(',') : null,
          subcategorias: filtrosActivos.subcategorias?.length > 0 ? filtrosActivos.subcategorias.join(',') : null
        };
        body.filtros = agregarFiltrosAvanzados(body.filtros);
      }

      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/productos/exportar-rebate',
        body,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `rebate_export_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      alert('Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      alert('Error al exportar');
    } finally {
      setExportando(false);
    }
  };

  const exportarClasica = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      let params = `porcentaje_adicional=${parseFloat(porcentajeClasica.toString().replace(',', '.')) || 0}`;

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock !== null) params += `&con_stock=${filtrosActivos.con_stock}`;
        if (filtrosActivos.con_precio !== null) params += `&con_precio=${filtrosActivos.con_precio}`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
        if (filtrosActivos.filtroRebate === 'con_rebate') params += `&con_rebate=true`;
        if (filtrosActivos.filtroRebate === 'sin_rebate') params += `&con_rebate=false`;
        if (filtrosActivos.filtroOferta === 'con_oferta') params += `&con_oferta=true`;
        if (filtrosActivos.filtroOferta === 'sin_oferta') params += `&con_oferta=false`;
        if (filtrosActivos.filtroWebTransf === 'con_web_transf') params += `&con_web_transf=true`;
        if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params += `&con_web_transf=false`;
        if (filtrosActivos.filtroMarkupClasica === 'positivo') params += `&markup_clasica_positivo=true`;
        if (filtrosActivos.filtroMarkupClasica === 'negativo') params += `&markup_clasica_positivo=false`;
        if (filtrosActivos.filtroMarkupRebate === 'positivo') params += `&markup_rebate_positivo=true`;
        if (filtrosActivos.filtroMarkupRebate === 'negativo') params += `&markup_rebate_positivo=false`;
        if (filtrosActivos.filtroMarkupOferta === 'positivo') params += `&markup_oferta_positivo=true`;
        if (filtrosActivos.filtroMarkupOferta === 'negativo') params += `&markup_oferta_positivo=false`;
        if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params += `&markup_web_transf_positivo=true`;
        if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params += `&markup_web_transf_positivo=false`;
        if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params += `&out_of_cards=true`;
        if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params += `&out_of_cards=false`;
        if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
        if (filtrosActivos.pmsSeleccionados?.length > 0) params += `&pms=${filtrosActivos.pmsSeleccionados.join(',')}`;
        if (filtrosActivos.audit_usuarios?.length > 0) params += `&audit_usuarios=${filtrosActivos.audit_usuarios.join(',')}`;
        if (filtrosActivos.audit_tipos_accion?.length > 0) params += `&audit_tipos_accion=${filtrosActivos.audit_tipos_accion.join(',')}`;
        if (filtrosActivos.audit_fecha_desde) params += `&audit_fecha_desde=${filtrosActivos.audit_fecha_desde}`;
        if (filtrosActivos.audit_fecha_hasta) params += `&audit_fecha_hasta=${filtrosActivos.audit_fecha_hasta}`;
      }

      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/exportar-clasica?${params}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `clasica_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      alert('Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      alert('Error al exportar Clásica');
    } finally {
      setExportando(false);
    }
  };

  const exportarWebTransf = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      let params = `porcentaje_adicional=${parseFloat(porcentajeWebTransf.toString().replace(',', '.')) || 0}`;

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock !== null) params += `&con_stock=${filtrosActivos.con_stock}`;
        if (filtrosActivos.con_precio !== null) params += `&con_precio=${filtrosActivos.con_precio}`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
        if (filtrosActivos.filtroRebate === 'con_rebate') params += `&con_rebate=true`;
        if (filtrosActivos.filtroRebate === 'sin_rebate') params += `&con_rebate=false`;
        if (filtrosActivos.filtroOferta === 'con_oferta') params += `&con_oferta=true`;
        if (filtrosActivos.filtroOferta === 'sin_oferta') params += `&con_oferta=false`;
        if (filtrosActivos.filtroWebTransf === 'con_web_transf') params += `&con_web_transf=true`;
        if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params += `&con_web_transf=false`;
        if (filtrosActivos.filtroMarkupClasica === 'positivo') params += `&markup_clasica_positivo=true`;
        if (filtrosActivos.filtroMarkupClasica === 'negativo') params += `&markup_clasica_positivo=false`;
        if (filtrosActivos.filtroMarkupRebate === 'positivo') params += `&markup_rebate_positivo=true`;
        if (filtrosActivos.filtroMarkupRebate === 'negativo') params += `&markup_rebate_positivo=false`;
        if (filtrosActivos.filtroMarkupOferta === 'positivo') params += `&markup_oferta_positivo=true`;
        if (filtrosActivos.filtroMarkupOferta === 'negativo') params += `&markup_oferta_positivo=false`;
        if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params += `&markup_web_transf_positivo=true`;
        if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params += `&markup_web_transf_positivo=false`;
        if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params += `&out_of_cards=true`;
        if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params += `&out_of_cards=false`;
        if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
        if (filtrosActivos.pmsSeleccionados?.length > 0) params += `&pms=${filtrosActivos.pmsSeleccionados.join(',')}`;
        if (filtrosActivos.audit_usuarios?.length > 0) params += `&audit_usuarios=${filtrosActivos.audit_usuarios.join(',')}`;
        if (filtrosActivos.audit_tipos_accion?.length > 0) params += `&audit_tipos_accion=${filtrosActivos.audit_tipos_accion.join(',')}`;
        if (filtrosActivos.audit_fecha_desde) params += `&audit_fecha_desde=${filtrosActivos.audit_fecha_desde}`;
        if (filtrosActivos.audit_fecha_hasta) params += `&audit_fecha_hasta=${filtrosActivos.audit_fecha_hasta}`;
      }

      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/exportar-web-transferencia?${params}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `web_transferencia_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      alert('Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      alert('Error al exportar Web Transferencia');
    } finally {
      setExportando(false);
    }
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <h2 className={styles.title}>📊 Exportar Precios</h2>
          <button onClick={onClose} className={styles.closeButton}>×</button>
        </div>

        <div className={styles.tabs}>
          <button
            onClick={() => setTab('rebate')}
            className={`${styles.tab} ${tab === 'rebate' ? styles.active : ''}`}
          >
            Rebate ML
          </button>
          <button
            onClick={() => setTab('web_transf')}
            className={`${styles.tab} ${tab === 'web_transf' ? styles.active : ''}`}
          >
            Web Transferencia
          </button>
          <button
            onClick={() => setTab('clasica')}
            className={`${styles.tab} ${tab === 'clasica' ? styles.active : ''}`}
          >
            Clásica
          </button>
        </div>

        <div className={styles.content}>
          {tab === 'rebate' && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <div className={styles.formGrid}>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Fecha Desde:</label>
                  <input
                    type="text"
                    placeholder="DD/MM/YYYY"
                    value={fechaDesde}
                    onChange={(e) => setFechaDesde(e.target.value)}
                    className={styles.input}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Fecha Hasta:</label>
                  <input
                    type="text"
                    placeholder="DD/MM/YYYY"
                    value={fechaHasta}
                    onChange={(e) => setFechaHasta(e.target.value)}
                    className={styles.input}
                  />
                </div>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarRebate} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Rebate'}
                </button>
              </div>
            </div>
          )}

          {tab === 'web_transf' && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <p className={styles.description}>
                Exporta los precios de Web Transferencia activos en formato Excel.
                <br />
                <strong>Formato:</strong> Código/EAN | Precio | ID Moneda (1=ARS)
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Porcentaje adicional (%):</label>
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="Ej: 25"
                  value={porcentajeWebTransf}
                  onChange={(e) => {
                    // Aceptar cualquier entrada, dejar que el usuario escriba libremente
                    setPorcentajeWebTransf(e.target.value);
                  }}
                  onBlur={(e) => {
                    // Al salir del campo, validar que sea un número válido
                    const valor = e.target.value.replace(',', '.');
                    const numero = parseFloat(valor);
                    if (!isNaN(numero)) {
                      setPorcentajeWebTransf(numero.toString());
                    } else {
                      setPorcentajeWebTransf('0');
                    }
                  }}
                  className={styles.input}
                />
                <small className={styles.filterInfo}>
                  Suma este porcentaje a los precios de Web Transferencia
                </small>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarWebTransf} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Excel'}
                </button>
              </div>
            </div>
          )}

          {tab === 'clasica' && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <p className={styles.description}>
                Exporta precios de Clásica. Si el producto tiene rebate activo, aplica el % sobre el precio rebate. Si no, exporta el precio clásica original.
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Porcentaje adicional sobre rebate (%):</label>
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="Ej: 20"
                  value={porcentajeClasica}
                  onChange={(e) => {
                    // Aceptar cualquier entrada, dejar que el usuario escriba libremente
                    setPorcentajeClasica(e.target.value);
                  }}
                  onBlur={(e) => {
                    // Al salir del campo, validar que sea un número válido
                    const valor = e.target.value.replace(',', '.');
                    const numero = parseFloat(valor);
                    if (!isNaN(numero)) {
                      setPorcentajeClasica(numero.toString());
                    } else {
                      setPorcentajeClasica('0');
                    }
                  }}
                  className={styles.input}
                />
                <small className={styles.filterInfo}>
                  Solo aplica a productos con rebate activo
                </small>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarClasica} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Excel'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
