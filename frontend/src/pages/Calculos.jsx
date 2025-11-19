import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/Calculos.css';

// Detectar si estamos en desarrollo o producción
const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000/api'
  : 'https://pricing.gaussonline.com.ar/api';

const Calculos = () => {
  const [calculos, setCalculos] = useState([]);
  const [calculoEditando, setCalculoEditando] = useState(null);
  const [formData, setFormData] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [tipoCambio, setTipoCambio] = useState(null);
  const [seleccionados, setSeleccionados] = useState(new Set());
  const [filtroExportar, setFiltroExportar] = useState('todos');

  useEffect(() => {
    cargarCalculos();
    cargarTipoCambio();
  }, []);

  const cargarTipoCambio = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('https://pricing.gaussonline.com.ar/api/tipo-cambio', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setTipoCambio(response.data.tipo_cambio);
    } catch (error) {
      console.error('Error cargando tipo de cambio:', error);
    }
  };

  const cargarCalculos = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('https://pricing.gaussonline.com.ar/api/calculos', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setCalculos(response.data);
    } catch (error) {
      console.error('Error cargando cálculos:', error);
    } finally {
      setCargando(false);
    }
  };

  const iniciarEdicion = (calculo) => {
    setCalculoEditando(calculo.id);
    setFormData({
      descripcion: calculo.descripcion,
      ean: calculo.ean || '',
      cantidad: calculo.cantidad || 0,
      costo: calculo.costo,
      moneda_costo: calculo.moneda_costo,
      iva: calculo.iva,
      comision_ml: calculo.comision_ml,
      costo_envio: calculo.costo_envio,
      precio_final: calculo.precio_final,
      tipo_cambio_usado: calculo.tipo_cambio_usado || tipoCambio
    });
  };

  const cancelarEdicion = () => {
    setCalculoEditando(null);
    setFormData(null);
  };

  const recalcular = (data) => {
    const costo = parseFloat(data.costo) || 0;
    const comisionML = parseFloat(data.comision_ml) || 0;
    const costoEnvio = parseFloat(data.costo_envio) || 0;
    const precioFinal = parseFloat(data.precio_final) || 0;
    const iva = parseFloat(data.iva);

    // Usar el tipo de cambio guardado en el cálculo, si existe
    // Si no, usar el actual, o 1425 como fallback
    const tcActual = data.tipo_cambio_usado || tipoCambio || 1425;

    const costoARS = data.moneda_costo === 'USD'
      ? costo * tcActual
      : costo;

    const baseComision = precioFinal * (comisionML / 100);
    const ivaComision = baseComision * (iva / 100);
    const comisionTotal = baseComision + ivaComision;

    const limpio = precioFinal - (precioFinal * (iva / 100)) - costoEnvio - comisionTotal;
    const markup = costoARS > 0 ? ((limpio - costoARS) / costoARS) * 100 : 0;

    return {
      markup_porcentaje: markup.toFixed(2),
      limpio: limpio.toFixed(2),
      comision_total: comisionTotal.toFixed(2),
      tipo_cambio_usado: tcActual
    };
  };

  const guardarEdicion = async () => {
    if (!formData.descripcion && !formData.ean) {
      alert('Debe proporcionar al menos descripción o EAN');
      return;
    }

    try {
      const resultados = recalcular(formData);
      const token = localStorage.getItem('token');

      await axios.put(
        `https://pricing.gaussonline.com.ar/api/calculos/${calculoEditando}`,
        {
          ...formData,
          ...resultados
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      await cargarCalculos();
      cancelarEdicion();
    } catch (error) {
      console.error('Error guardando cambios:', error);
      alert('Error al guardar los cambios');
    }
  };

  const actualizarCantidad = async (id, cantidad) => {
    try {
      const token = localStorage.getItem('token');
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/calculos/${id}/cantidad`,
        { cantidad: parseInt(cantidad) || 0 },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      // Actualizar solo el cálculo específico en el estado
      setCalculos(calculos.map(c =>
        c.id === id ? { ...c, cantidad: parseInt(cantidad) || 0 } : c
      ));
    } catch (error) {
      console.error('Error actualizando cantidad:', error);
      alert('Error al actualizar la cantidad');
    }
  };

  const toggleSeleccion = (id) => {
    const nuevosSeleccionados = new Set(seleccionados);
    if (nuevosSeleccionados.has(id)) {
      nuevosSeleccionados.delete(id);
    } else {
      nuevosSeleccionados.add(id);
    }
    setSeleccionados(nuevosSeleccionados);
  };

  const toggleSeleccionTodos = () => {
    if (seleccionados.size === calculos.length) {
      setSeleccionados(new Set());
    } else {
      setSeleccionados(new Set(calculos.map(c => c.id)));
    }
  };

  const eliminarCalculo = async (id) => {
    if (!confirm('¿Está seguro que desea eliminar este cálculo?')) {
      return;
    }

    try {
      const token = localStorage.getItem('token');
      await axios.delete(`https://pricing.gaussonline.com.ar/api/calculos/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      await cargarCalculos();
      setSeleccionados(new Set());
    } catch (error) {
      console.error('Error eliminando cálculo:', error);
      alert('Error al eliminar el cálculo');
    }
  };

  const eliminarMasivo = async () => {
    let idsAEliminar = [];

    if (filtroExportar === 'seleccionados') {
      if (seleccionados.size === 0) {
        alert('No hay elementos seleccionados');
        return;
      }
      idsAEliminar = Array.from(seleccionados);
    } else if (filtroExportar === 'con_cantidad') {
      idsAEliminar = calculos.filter(c => c.cantidad > 0).map(c => c.id);
      if (idsAEliminar.length === 0) {
        alert('No hay cálculos con cantidad > 0');
        return;
      }
    } else {
      idsAEliminar = calculos.map(c => c.id);
    }

    if (!confirm(`¿Está seguro que desea eliminar ${idsAEliminar.length} cálculo(s)?`)) {
      return;
    }

    try {
      const token = localStorage.getItem('token');
      await axios.post(
        'https://pricing.gaussonline.com.ar/api/calculos/acciones/eliminar-masivo',
        { calculo_ids: idsAEliminar },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      await cargarCalculos();
      setSeleccionados(new Set());
    } catch (error) {
      console.error('Error eliminando cálculos:', error);
      alert('Error al eliminar los cálculos');
    }
  };

  const exportarExcel = async () => {
    let queryParams = `filtro=${filtroExportar}`;

    if (filtroExportar === 'seleccionados') {
      if (seleccionados.size === 0) {
        alert('No hay elementos seleccionados');
        return;
      }
      queryParams += `&ids=${Array.from(seleccionados).join(',')}`;
    }

    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `${API_BASE_URL}/calculos/exportar/excel?${queryParams}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );

      // Crear link de descarga
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;

      // Extraer nombre de archivo del header o usar default
      const contentDisposition = response.headers['content-disposition'];
      const filename = contentDisposition
        ? contentDisposition.split('filename=')[1].replace(/"/g, '')
        : `calculos_${filtroExportar}_${new Date().getTime()}.xlsx`;

      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exportando:', error);
      if (error.response) {
        // El servidor respondió con un código de estado fuera del rango 2xx
        alert(`Error al exportar: ${error.response.status} - ${error.response.data?.detail || 'Error del servidor'}`);
      } else if (error.request) {
        // La solicitud se hizo pero no hubo respuesta
        alert('Error de conexión al servidor. Verifica que el backend esté corriendo.');
      } else {
        // Algo sucedió al configurar la solicitud
        alert(`Error: ${error.message}`);
      }
    }
  };

  const getMarkupColor = (markup) => {
    const valor = parseFloat(markup);
    if (valor >= 30) return '#22c55e';
    if (valor >= 15) return '#f59e0b';
    return '#ef4444';
  };

  if (cargando) {
    return (
      <div className="calculos-container">
        <p>Cargando...</p>
      </div>
    );
  }

  return (
    <div className="calculos-container">
      <div className="calculos-header">
        <h1>Cálculos de Pricing</h1>
        <p className="subtitle">Historial de cálculos guardados</p>
      </div>

      {calculos.length === 0 ? (
        <div className="empty-state">
          <p>No hay cálculos guardados</p>
          <p className="hint">Presiona <kbd>Ctrl</kbd> + <kbd>P</kbd> para abrir la calculadora</p>
        </div>
      ) : (
        <>
          <div className="acciones-masivas-bar">
            <div className="acciones-left">
              <label>
                <input
                  type="checkbox"
                  checked={seleccionados.size === calculos.length && calculos.length > 0}
                  onChange={toggleSeleccionTodos}
                />
                Seleccionar todos ({seleccionados.size})
              </label>
            </div>

            <div className="acciones-center">
              <select
                value={filtroExportar}
                onChange={(e) => setFiltroExportar(e.target.value)}
                className="filtro-select"
              >
                <option value="todos">Todos los cálculos</option>
                <option value="con_cantidad">Solo con cantidad</option>
                <option value="seleccionados">Seleccionados ({seleccionados.size})</option>
              </select>
            </div>

            <div className="acciones-right">
              <button onClick={exportarExcel} className="btn-exportar">
                📥 Exportar Excel
              </button>
              <button onClick={eliminarMasivo} className="btn-eliminar-masivo">
                🗑 Eliminar
              </button>
            </div>
          </div>

          <div className="calculos-table-wrapper">
            <table className="calculos-table">
              <thead>
                <tr>
                  <th style={{ width: '40px' }}>✓</th>
                  <th>Descripción</th>
                  <th>EAN</th>
                  <th>Cant.</th>
                  <th>Costo</th>
                  <th>Moneda</th>
                  <th>TC Usado</th>
                  <th>IVA</th>
                  <th>Comisión ML</th>
                  <th>Envío</th>
                  <th>Precio Final</th>
                  <th>Markup</th>
                  <th>Limpio</th>
                  <th>Fecha</th>
                  <th>Acciones</th>
                </tr>
              </thead>
            <tbody>
              {calculos.map((calculo) => (
                <tr key={calculo.id}>
                  {calculoEditando === calculo.id ? (
                    <>
                      <td>
                        <input
                          type="checkbox"
                          checked={seleccionados.has(calculo.id)}
                          onChange={() => toggleSeleccion(calculo.id)}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={formData.descripcion}
                          onChange={(e) => setFormData({ ...formData, descripcion: e.target.value })}
                          className="edit-input"
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={formData.ean}
                          onChange={(e) => setFormData({ ...formData, ean: e.target.value })}
                          className="edit-input"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.cantidad}
                          onChange={(e) => setFormData({ ...formData, cantidad: e.target.value })}
                          className="edit-input small"
                          min="0"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.costo}
                          onChange={(e) => setFormData({ ...formData, costo: e.target.value })}
                          className="edit-input small"
                          step="0.01"
                        />
                      </td>
                      <td>
                        <select
                          value={formData.moneda_costo}
                          onChange={(e) => setFormData({ ...formData, moneda_costo: e.target.value })}
                          className="edit-input"
                        >
                          <option value="USD">USD</option>
                          <option value="ARS">ARS</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.tipo_cambio_usado || ''}
                          onChange={(e) => setFormData({ ...formData, tipo_cambio_usado: e.target.value })}
                          className="edit-input small"
                          step="0.01"
                          placeholder="TC"
                        />
                      </td>
                      <td>
                        <select
                          value={formData.iva}
                          onChange={(e) => setFormData({ ...formData, iva: e.target.value })}
                          className="edit-input"
                        >
                          <option value="10.5">10.5%</option>
                          <option value="21">21%</option>
                        </select>
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.comision_ml}
                          onChange={(e) => setFormData({ ...formData, comision_ml: e.target.value })}
                          className="edit-input small"
                          step="0.01"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.costo_envio}
                          onChange={(e) => setFormData({ ...formData, costo_envio: e.target.value })}
                          className="edit-input small"
                          step="0.01"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.precio_final}
                          onChange={(e) => setFormData({ ...formData, precio_final: e.target.value })}
                          className="edit-input small"
                          step="0.01"
                        />
                      </td>
                      <td colSpan="4" style={{ textAlign: 'center', fontStyle: 'italic', color: '#6b7280' }}>
                        Se recalculará al guardar
                      </td>
                      <td>
                        <div className="action-buttons">
                          <button onClick={guardarEdicion} className="btn-save">✓</button>
                          <button onClick={cancelarEdicion} className="btn-cancel">✗</button>
                        </div>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>
                        <input
                          type="checkbox"
                          checked={seleccionados.has(calculo.id)}
                          onChange={() => toggleSeleccion(calculo.id)}
                        />
                      </td>
                      <td>{calculo.descripcion}</td>
                      <td>{calculo.ean || '-'}</td>
                      <td>
                        <input
                          type="number"
                          value={calculo.cantidad || 0}
                          onChange={(e) => actualizarCantidad(calculo.id, e.target.value)}
                          className="cantidad-input"
                          min="0"
                          style={{ width: '60px', textAlign: 'center' }}
                        />
                      </td>
                      <td>${parseFloat(calculo.costo).toLocaleString('es-AR', { minimumFractionDigits: 2 })}</td>
                      <td>{calculo.moneda_costo}</td>
                      <td>{calculo.tipo_cambio_usado ? parseFloat(calculo.tipo_cambio_usado).toFixed(2) : '-'}</td>
                      <td>{calculo.iva}%</td>
                      <td>{calculo.comision_ml}%</td>
                      <td>${parseFloat(calculo.costo_envio).toLocaleString('es-AR', { minimumFractionDigits: 2 })}</td>
                      <td>${parseFloat(calculo.precio_final).toLocaleString('es-AR', { minimumFractionDigits: 2 })}</td>
                      <td style={{ color: getMarkupColor(calculo.markup_porcentaje), fontWeight: 'bold' }}>
                        {parseFloat(calculo.markup_porcentaje).toFixed(2)}%
                      </td>
                      <td>${parseFloat(calculo.limpio).toLocaleString('es-AR', { minimumFractionDigits: 2 })}</td>
                      <td>{new Date(calculo.fecha_creacion).toLocaleDateString('es-AR')}</td>
                      <td>
                        <div className="action-buttons">
                          <button onClick={() => iniciarEdicion(calculo)} className="btn-edit">✎</button>
                          <button onClick={() => eliminarCalculo(calculo.id)} className="btn-delete">🗑</button>
                        </div>
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </>
      )}
    </div>
  );
};

export default Calculos;
