import { useState, useEffect } from 'react';
import api from '../services/api';

/**
 * Manages audit-related state and loaders for the Productos page.
 * Leaf hook: owns its own endpoints.
 * @param {{ showToast: Function }} params
 */
export function useProductosAuditoria({ showToast }) {
  const [auditoriaVisible, setAuditoriaVisible] = useState(false);
  const [auditoriaData, setAuditoriaData] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [tiposAccion, setTiposAccion] = useState([]);

  const cargarUsuariosAuditoria = async () => {
    try {
      const response = await api.get('/auditoria/usuarios');
      setUsuarios(response.data.usuarios);
    } catch {
      showToast('Error al cargar usuarios', 'error');
    }
  };

  const cargarTiposAccion = async () => {
    try {
      const response = await api.get('/auditoria/tipos-accion');
      setTiposAccion(response.data.tipos);
    } catch {
      showToast('Error al cargar tipos de acción', 'error');
    }
  };

  const verAuditoria = async (productoId) => {
    try {
      const response = await api.get(`/productos/${productoId}/auditoria`);
      setAuditoriaData(response.data);
      setAuditoriaVisible(true);
    } catch {
      showToast('Error al cargar el historial', 'error');
    }
  };

  // Bootstrap on mount
  useEffect(() => {
    cargarUsuariosAuditoria();
    cargarTiposAccion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    auditoriaVisible,
    setAuditoriaVisible,
    auditoriaData,
    usuarios,
    tiposAccion,
    verAuditoria,
    cargarUsuariosAuditoria,
    cargarTiposAccion,
  };
}
