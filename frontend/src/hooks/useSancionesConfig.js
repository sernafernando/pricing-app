import { useState, useEffect, useCallback } from 'react';
import { rrhhAPI } from '../services/api';

/**
 * Hook para manejar la configuración de sanciones: tipos + textos predefinidos.
 *
 * Encapsula: fetch, CRUD, state de formularios, tabs del config modal.
 */
export default function useSancionesConfig() {
  // ── Shared ──
  const [configModalOpen, setConfigModalOpen] = useState(false);
  const [configTab, setConfigTab] = useState('tipos');

  // ── Tipos ──
  const [tiposSancion, setTiposSancion] = useState([]);
  const [editingTipo, setEditingTipo] = useState(null);
  const [tipoForm, setTipoForm] = useState({ nombre: '', descripcion: '', requiere_descuento: false, orden: 0 });
  const [tipoSaving, setTipoSaving] = useState(false);
  const [tipoError, setTipoError] = useState(null);

  // ── Textos predefinidos ──
  const [textosPredefinidos, setTextosPredefinidos] = useState([]);
  const [textosPredLoading, setTextosPredLoading] = useState(false);
  const [editingTexto, setEditingTexto] = useState(null);
  const [textoForm, setTextoForm] = useState({ nombre: '', texto: '', orden: 0 });
  const [textoSaving, setTextoSaving] = useState(false);
  const [textoError, setTextoError] = useState(null);
  const [deleteConfirmTexto, setDeleteConfirmTexto] = useState(null);

  // ── Derived ──
  const tiposActivos = tiposSancion.filter((t) => t.activo);
  const textosActivos = textosPredefinidos.filter((t) => t.activo);

  // ── Fetch ──
  const reloadTipos = useCallback(async () => {
    try {
      const { data } = await rrhhAPI.listarTiposSancion({ incluir_inactivos: true });
      setTiposSancion(Array.isArray(data) ? data : data.items || []);
    } catch {
      setTipoError('Error al recargar tipos');
    }
  }, []);

  const reloadTextosPredefinidos = useCallback(async () => {
    setTextosPredLoading(true);
    try {
      const { data } = await rrhhAPI.listarTextosPredefinidosSancion({ activo: false });
      setTextosPredefinidos(Array.isArray(data) ? data : data.items || []);
    } catch {
      setTextoError('Error al cargar textos predefinidos');
    } finally {
      setTextosPredLoading(false);
    }
  }, []);

  useEffect(() => {
    reloadTipos();
    reloadTextosPredefinidos();
  }, [reloadTipos, reloadTextosPredefinidos]);

  // ── Tipos CRUD ──
  const openEditTipo = (tipo) => {
    setEditingTipo(tipo);
    setTipoForm({
      nombre: tipo.nombre,
      descripcion: tipo.descripcion || '',
      requiere_descuento: tipo.requiere_descuento,
      orden: tipo.orden,
    });
    setTipoError(null);
  };

  const openNewTipo = () => {
    setEditingTipo(null);
    setTipoForm({ nombre: '', descripcion: '', requiere_descuento: false, orden: tiposSancion.length + 1 });
    setTipoError(null);
  };

  const handleSaveTipo = async () => {
    if (!tipoForm.nombre.trim()) {
      setTipoError('El nombre es obligatorio');
      return;
    }
    setTipoSaving(true);
    setTipoError(null);
    try {
      if (editingTipo) {
        await rrhhAPI.actualizarTipoSancion(editingTipo.id, tipoForm);
      } else {
        await rrhhAPI.crearTipoSancion(tipoForm);
      }
      await reloadTipos();
      setEditingTipo(null);
      setTipoForm({ nombre: '', descripcion: '', requiere_descuento: false, orden: 0 });
    } catch (err) {
      setTipoError(err.response?.data?.detail || 'Error al guardar tipo');
    } finally {
      setTipoSaving(false);
    }
  };

  const handleToggleTipoActivo = async (tipo) => {
    try {
      await rrhhAPI.actualizarTipoSancion(tipo.id, { activo: !tipo.activo });
      await reloadTipos();
    } catch {
      setTipoError('Error al cambiar estado del tipo');
    }
  };

  // ── Textos predefinidos CRUD ──
  const openEditTexto = (texto) => {
    setEditingTexto(texto);
    setTextoForm({ nombre: texto.nombre, texto: texto.texto, orden: texto.orden });
    setTextoError(null);
  };

  const openNewTexto = () => {
    setEditingTexto(null);
    setTextoForm({ nombre: '', texto: '', orden: textosPredefinidos.length + 1 });
    setTextoError(null);
  };

  const handleSaveTexto = async () => {
    if (!textoForm.nombre.trim()) {
      setTextoError('El nombre es obligatorio');
      return;
    }
    if (!textoForm.texto.trim()) {
      setTextoError('El texto es obligatorio');
      return;
    }
    setTextoSaving(true);
    setTextoError(null);
    try {
      if (editingTexto) {
        await rrhhAPI.actualizarTextoPredefinidoSancion(editingTexto.id, textoForm);
      } else {
        await rrhhAPI.crearTextoPredefinidoSancion(textoForm);
      }
      await reloadTextosPredefinidos();
      setEditingTexto(null);
      setTextoForm({ nombre: '', texto: '', orden: 0 });
    } catch (err) {
      setTextoError(err.response?.data?.detail || 'Error al guardar texto');
    } finally {
      setTextoSaving(false);
    }
  };

  const handleDeleteTexto = async () => {
    if (!deleteConfirmTexto) return;
    try {
      await rrhhAPI.eliminarTextoPredefinidoSancion(deleteConfirmTexto.id);
      await reloadTextosPredefinidos();
    } catch {
      setTextoError('Error al desactivar texto predefinido');
    } finally {
      setDeleteConfirmTexto(null);
    }
  };

  const closeConfigModal = () => {
    setConfigModalOpen(false);
    setEditingTipo(null);
    setEditingTexto(null);
  };

  return {
    // Config modal
    configModalOpen, setConfigModalOpen, closeConfigModal,
    configTab, setConfigTab,
    // Tipos
    tiposSancion, tiposActivos,
    editingTipo, tipoForm, setTipoForm, tipoSaving, tipoError,
    openEditTipo, openNewTipo, handleSaveTipo, handleToggleTipoActivo,
    // Textos predefinidos
    textosPredefinidos, textosActivos, textosPredLoading,
    editingTexto, textoForm, setTextoForm, textoSaving, textoError,
    deleteConfirmTexto, setDeleteConfirmTexto,
    openEditTexto, openNewTexto, handleSaveTexto, handleDeleteTexto,
  };
}
