import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/Calculos.css';

const Calculos = () => {
  const [calculos, setCalculos] = useState([]);
  const [calculoEditando, setCalculoEditando] = useState(null);
  const [formData, setFormData] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [tipoCambio, setTipoCambio] = useState(null);

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
      costo: calculo.costo,
      moneda_costo: calculo.moneda_costo,
      iva: calculo.iva,
      comision_ml: calculo.comision_ml,
      costo_envio: calculo.costo_envio,
      precio_final: calculo.precio_final
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

    const costoARS = data.moneda_costo === 'USD' && tipoCambio
      ? costo * tipoCambio
      : costo;

    const baseComision = precioFinal * (comisionML / 100);
    const ivaComision = baseComision * (iva / 100);
    const comisionTotal = baseComision + ivaComision;

    const limpio = precioFinal - (precioFinal * (iva / 100)) - costoEnvio - comisionTotal;
    const markup = ((limpio - costoARS) / costoARS) * 100;

    return {
      markup_porcentaje: markup.toFixed(2),
      limpio: limpio.toFixed(2),
      comision_total: comisionTotal.toFixed(2)
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
    } catch (error) {
      console.error('Error eliminando cálculo:', error);
      alert('Error al eliminar el cálculo');
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
          <p className="hint">Presiona <kbd>Ctrl</kbd> + <kbd>K</kbd> para abrir la calculadora</p>
        </div>
      ) : (
        <div className="calculos-table-wrapper">
          <table className="calculos-table">
            <thead>
              <tr>
                <th>Descripción</th>
                <th>EAN</th>
                <th>Costo</th>
                <th>Moneda</th>
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
                          value={formData.costo}
                          onChange={(e) => setFormData({ ...formData, costo: e.target.value })}
                          className="edit-input small"
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
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.costo_envio}
                          onChange={(e) => setFormData({ ...formData, costo_envio: e.target.value })}
                          className="edit-input small"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          value={formData.precio_final}
                          onChange={(e) => setFormData({ ...formData, precio_final: e.target.value })}
                          className="edit-input small"
                        />
                      </td>
                      <td colSpan="3" style={{ textAlign: 'center', fontStyle: 'italic', color: '#6b7280' }}>
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
                      <td>{calculo.descripcion}</td>
                      <td>{calculo.ean || '-'}</td>
                      <td>${parseFloat(calculo.costo).toLocaleString('es-AR', { minimumFractionDigits: 2 })}</td>
                      <td>{calculo.moneda_costo}</td>
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
      )}
    </div>
  );
};

export default Calculos;
