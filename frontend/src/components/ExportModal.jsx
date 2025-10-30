import { useState } from 'react';
import axios from 'axios';

export default function ExportModal({ onClose, filtrosActivos }) {  // ← AGREGAR filtrosActivos
  const [tab, setTab] = useState('rebate');
  const [exportando, setExportando] = useState(false);
  const [aplicarFiltros, setAplicarFiltros] = useState(false);
  const [porcentajeClasica, setPorcentajeClasica] = useState(0);
  
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
    (filtrosActivos?.audit_usuarios?.length > 0) ||
    (filtrosActivos?.audit_tipos_accion?.length > 0) ||
    !!filtrosActivos?.audit_fecha_desde ||
    !!filtrosActivos?.audit_fecha_hasta;

  // Función auxiliar para agregar filtros avanzados a los parámetros
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
    if (filtrosActivos.audit_usuarios?.length > 0) params.audit_usuarios = filtrosActivos.audit_usuarios.join(',');
    if (filtrosActivos.audit_tipos_accion?.length > 0) params.audit_tipos_accion = filtrosActivos.audit_tipos_accion.join(',');
    if (filtrosActivos.audit_fecha_desde) params.audit_fecha_desde = filtrosActivos.audit_fecha_desde;
    if (filtrosActivos.audit_fecha_hasta) params.audit_fecha_hasta = filtrosActivos.audit_fecha_hasta;
    return params;
  };

  // Componente para mostrar los filtros activos
  const FiltrosActivosDisplay = () => (
    <>
      {filtrosActivos?.search && <div>• Búsqueda: "{filtrosActivos.search}"</div>}
      {filtrosActivos?.con_stock === true && <div>• Con stock</div>}
      {filtrosActivos?.con_stock === false && <div>• Sin stock</div>}
      {filtrosActivos?.con_precio === true && <div>• Con precio</div>}
      {filtrosActivos?.con_precio === false && <div>• Sin precio</div>}
      {filtrosActivos?.marcas?.length > 0 && <div>• {filtrosActivos.marcas.length} marca(s)</div>}
      {filtrosActivos?.subcategorias?.length > 0 && <div>• {filtrosActivos.subcategorias.length} subcategoría(s)</div>}

      {/* Filtros Avanzados */}
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
    </>
  );
  
  // Estados para rebate
  const [fechaDesde, setFechaDesde] = useState(() => {
    const hoy = new Date();
    return hoy.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });
  const [fechaHasta, setFechaHasta] = useState(() => {
    const hoy = new Date();
    const ultimoDia = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0);
    return ultimoDia.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });

  // Estado para web transferencia
  const [porcentajeWebTransf, setPorcentajeWebTransf] = useState(0);

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

      // Agregar filtros si están activos
      if (aplicarFiltros) {
        body.filtros = {
          search: filtrosActivos.search || null,
          con_stock: filtrosActivos.con_stock,
          con_precio: filtrosActivos.con_precio,
          marcas: filtrosActivos.marcas?.length > 0 ? filtrosActivos.marcas.join(',') : null,
          subcategorias: filtrosActivos.subcategorias?.length > 0 ? filtrosActivos.subcategorias.join(',') : null
        };
        // Agregar filtros avanzados
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

      // Construir parámetros
      let params = `porcentaje_adicional=${porcentajeClasica}`;

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock !== null) params += `&con_stock=${filtrosActivos.con_stock}`;
        if (filtrosActivos.con_precio !== null) params += `&con_precio=${filtrosActivos.con_precio}`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;

        // Agregar filtros avanzados
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

      // Construir parámetros
      let params = `porcentaje_adicional=${porcentajeWebTransf}`;

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock !== null) params += `&con_stock=${filtrosActivos.con_stock}`;
        if (filtrosActivos.con_precio !== null) params += `&con_precio=${filtrosActivos.con_precio}`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;

        // Agregar filtros avanzados
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
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: 'white',
        borderRadius: '12px',
        maxWidth: '500px',
        width: '90%',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid #e5e7eb',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>
            📊 Exportar Precios
          </h2>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '24px',
              cursor: 'pointer',
              color: '#6b7280',
              padding: 0
            }}
          >
            ×
          </button>
        </div>

        {/* Pestañas */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid #e5e7eb'
        }}>
          <button
            onClick={() => setTab('rebate')}
            style={{
              flex: 1,
              padding: '12px 20px',
              background: 'none',
              border: 'none',
              borderBottom: tab === 'rebate' ? '3px solid #10b981' : '3px solid transparent',
              color: tab === 'rebate' ? '#10b981' : '#6b7280',
              fontWeight: tab === 'rebate' ? '600' : '400',
              cursor: 'pointer',
              fontSize: '14px',
              transition: 'all 0.2s'
            }}
          >
            Rebate ML
          </button>
          <button
            onClick={() => setTab('web_transf')}
            style={{
              flex: 1,
              padding: '12px 20px',
              background: 'none',
              border: 'none',
              borderBottom: tab === 'web_transf' ? '3px solid #10b981' : '3px solid transparent',
              color: tab === 'web_transf' ? '#10b981' : '#6b7280',
              fontWeight: tab === 'web_transf' ? '600' : '400',
              cursor: 'pointer',
              fontSize: '14px',
              transition: 'all 0.2s'
            }}
          >
            Web Transferencia
          </button>
          <button
            onClick={() => setTab('clasica')}
            style={{
              flex: 1,
              padding: '12px 20px',
              background: 'none',
              border: 'none',
              borderBottom: tab === 'clasica' ? '3px solid #10b981' : '3px solid transparent',
              color: tab === 'clasica' ? '#10b981' : '#6b7280',
              fontWeight: tab === 'clasica' ? '600' : '400',
              cursor: 'pointer',
              fontSize: '14px',
              transition: 'all 0.2s'
            }}
          >
            Clásica
          </button>
        </div>

        {/* Contenido */}
        <div style={{ padding: '24px' }}>
          {tab === 'rebate' ? (
            <div>
              {/* Selector de ámbito para Rebate */}
              {hayFiltros && (
                <div style={{
                  marginBottom: '16px',
                  padding: '12px',
                  background: '#f0fdf4',
                  border: '1px solid #86efac',
                  borderRadius: '8px'
                }}>
                  <label style={{
                    display: 'flex',
                    alignItems: 'center',
                    cursor: 'pointer',
                    fontWeight: '500'
                  }}>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                      style={{ marginRight: '8px' }}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && (
                    <div style={{ marginTop: '8px', fontSize: '13px', color: '#059669' }}>
                      <FiltrosActivosDisplay />
                    </div>
                  )}
                </div>
              )}
              
              <div style={{ display: 'grid', gap: '16px', marginBottom: '20px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
                    Fecha Desde:
                  </label>
                  <input
                    type="text"
                    placeholder="DD/MM/YYYY"
                    value={fechaDesde}
                    onChange={(e) => setFechaDesde(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '10px',
                      borderRadius: '6px',
                      border: '1px solid #d1d5db',
                      fontSize: '14px',
                      boxSizing: 'border-box'
                    }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
                    Fecha Hasta:
                  </label>
                  <input
                    type="text"
                    placeholder="DD/MM/YYYY"
                    value={fechaHasta}
                    onChange={(e) => setFechaHasta(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '10px',
                      borderRadius: '6px',
                      border: '1px solid #d1d5db',
                      fontSize: '14px',
                      boxSizing: 'border-box'
                    }}
                  />
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                <button
                  onClick={onClose}
                  disabled={exportando}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '6px',
                    border: '1px solid #d1d5db',
                    background: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer'
                  }}
                >
                  Cancelar
                </button>
                <button
                  onClick={exportarRebate}
                  disabled={exportando}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '6px',
                    border: 'none',
                    background: exportando ? '#9ca3af' : '#10b981',
                    color: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer',
                    fontWeight: '600'
                  }}
                >
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Rebate'}
                </button>
              </div>
            </div>
          ) : tab === 'web_transf' ? (
            <div>
              {/* Selector de ámbito para Web Transf */}
              {hayFiltros && (
                <div style={{
                  marginBottom: '16px',
                  padding: '12px',
                  background: '#f0fdf4',
                  border: '1px solid #86efac',
                  borderRadius: '8px'
                }}>
                  <label style={{
                    display: 'flex',
                    alignItems: 'center',
                    cursor: 'pointer',
                    fontWeight: '500'
                  }}>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                      style={{ marginRight: '8px' }}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && (
                    <div style={{ marginTop: '8px', fontSize: '13px', color: '#059669' }}>
                      <FiltrosActivosDisplay />
                    </div>
                  )}
                </div>
              )}
              
              <p style={{ color: '#6b7280', marginBottom: '16px', fontSize: '14px' }}>
                Exporta los precios de Web Transferencia activos en formato Excel.
                <br />
                <strong>Formato:</strong> Código/EAN | Precio | ID Moneda (1=ARS)
              </p>
              
              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
                  Porcentaje adicional (%):
                </label>
                <input
                  type="number"
                  placeholder="Ej: 25"
                  value={porcentajeWebTransf}
                  onChange={(e) => setPorcentajeWebTransf(parseFloat(e.target.value) || 0)}
                  style={{
                    width: '100%',
                    padding: '10px',
                    borderRadius: '6px',
                    border: '1px solid #d1d5db',
                    fontSize: '14px',
                    boxSizing: 'border-box'
                  }}
                />
                <small style={{ color: '#6b7280', fontSize: '12px', marginTop: '4px', display: 'block' }}>
                  Suma este porcentaje a los precios de Web Transferencia
                </small>
              </div>

              <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                <button
                  onClick={onClose}
                  disabled={exportando}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '6px',
                    border: '1px solid #d1d5db',
                    background: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer'
                  }}
                >
                  Cancelar
                </button>
                <button
                  onClick={exportarWebTransf}
                  disabled={exportando}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '6px',
                    border: 'none',
                    background: exportando ? '#9ca3af' : '#10b981',
                    color: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer',
                    fontWeight: '600'
                  }}
                >
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Excel'}
                </button>
              </div>
                     </div>
        ) : tab === 'clasica' ? (
          <div>
            {/* Selector de ámbito para Clásica */}
            {hayFiltros && (
              <div style={{
                marginBottom: '16px',
                padding: '12px',
                background: '#f0fdf4',
                border: '1px solid #86efac',
                borderRadius: '8px'
              }}>
                <label style={{
                  display: 'flex',
                  alignItems: 'center',
                  cursor: 'pointer',
                  fontWeight: '500'
                }}>
                  <input
                    type="checkbox"
                    checked={aplicarFiltros}
                    onChange={(e) => setAplicarFiltros(e.target.checked)}
                    style={{ marginRight: '8px' }}
                  />
                  Exportar solo productos filtrados
                </label>
                {aplicarFiltros && (
                  <div style={{ marginTop: '8px', fontSize: '13px', color: '#059669' }}>
                    {filtrosActivos?.search && <div>• Búsqueda: "{filtrosActivos.search}"</div>}
                    {filtrosActivos?.con_stock === true && <div>• Con stock</div>}
                    {filtrosActivos?.con_stock === false && <div>• Sin stock</div>}
                    {filtrosActivos?.con_precio === true && <div>• Con precio</div>}
                    {filtrosActivos?.con_precio === false && <div>• Sin precio</div>}
                    {filtrosActivos?.marcas?.length > 0 && <div>• {filtrosActivos.marcas.length} marca(s)</div>}
                    {filtrosActivos?.subcategorias?.length > 0 && <div>• {filtrosActivos.subcategorias.length} subcategoría(s)</div>}
                  </div>
                )}
              </div>
            )}
            
            <p style={{ color: '#6b7280', marginBottom: '16px', fontSize: '14px' }}>
              Exporta precios de Clásica. Si el producto tiene rebate activo, aplica el % sobre el precio rebate. Si no, exporta el precio clásica original.
            </p>
            
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
                Porcentaje adicional sobre rebate (%):
              </label>
              <input
                type="number"
                placeholder="Ej: 20"
                value={porcentajeClasica}
                onChange={(e) => setPorcentajeClasica(parseFloat(e.target.value) || 0)}
                style={{
                  width: '100%',
                  padding: '10px',
                  borderRadius: '6px',
                  border: '1px solid #d1d5db',
                  fontSize: '14px',
                  boxSizing: 'border-box'
                }}
              />
              <small style={{ color: '#6b7280', fontSize: '12px', marginTop: '4px', display: 'block' }}>
                Solo aplica a productos con rebate activo
              </small>
            </div>

            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                onClick={onClose}
                disabled={exportando}
                style={{
                  padding: '10px 20px',
                  borderRadius: '6px',
                  border: '1px solid #d1d5db',
                  background: 'white',
                  cursor: exportando ? 'not-allowed' : 'pointer'
                }}
              >
                Cancelar
              </button>
              <button
                onClick={exportarClasica}
                disabled={exportando}
                style={{
                  padding: '10px 20px',
                  borderRadius: '6px',
                  border: 'none',
                  background: exportando ? '#9ca3af' : '#10b981',
                  color: 'white',
                  cursor: exportando ? 'not-allowed' : 'pointer',
                  fontWeight: '600'
                }}
              >
                {exportando ? '⏳ Exportando...' : '📥 Exportar Excel'}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  </div>
);
}
