/**
 * RMA Admin Opciones - Panel de gestión de dropdowns configurables.
 *
 * Permite al admin crear, editar, activar/desactivar opciones
 * agrupadas por categoría. Cada categoría corresponde a un dropdown
 * del módulo RMA (estado_recepcion, causa_devolucion, etc.)
 */

import { useState, useEffect } from 'react';
import { Plus, Pencil, Check, X, ToggleLeft, ToggleRight, Settings } from 'lucide-react';
import api from '../services/api';
import styles from './RmaAdminOpciones.module.css';

const COLORES_DISPONIBLES = [
  { nombre: 'green', hex: '#22c55e' },
  { nombre: 'blue', hex: '#3b82f6' },
  { nombre: 'yellow', hex: '#eab308' },
  { nombre: 'orange', hex: '#f97316' },
  { nombre: 'red', hex: '#ef4444' },
  { nombre: 'purple', hex: '#a855f7' },
  { nombre: 'gray', hex: '#6b7280' },
];

const CATEGORIA_LABELS = {
  estado_caso: 'Estado del Caso',
  estado_recepcion: 'Estado de Recepción',
  causa_devolucion: 'Causa de Devolución',
  apto_venta: 'Apto para la Venta',
  estado_revision: 'Estado de Revisión',
  estado_reclamo_ml: 'Estado Reclamo ML',
  cobertura_ml: 'Cobertura ML',
  estado_proceso: 'Estado del Proceso',
  deposito_destino: 'Depósito Destino',
  estado_proveedor: 'Estado Proveedor',
};

const getColorHex = (nombre) => {
  const found = COLORES_DISPONIBLES.find((c) => c.nombre === nombre);
  return found ? found.hex : '#6b7280';
};

export default function RmaAdminOpciones() {
  const [categorias, setCategorias] = useState([]);
  const [categoriaActiva, setCategoriaActiva] = useState(null);
  const [opciones, setOpciones] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Form nueva opción
  const [showForm, setShowForm] = useState(false);
  const [nuevoValor, setNuevoValor] = useState('');
  const [nuevoOrden, setNuevoOrden] = useState(0);
  const [nuevoColor, setNuevoColor] = useState('gray');
  const [nuevaCategoria, setNuevaCategoria] = useState('');
  const [saving, setSaving] = useState(false);

  // Edición inline
  const [editandoId, setEditandoId] = useState(null);
  const [editValor, setEditValor] = useState('');
  const [editOrden, setEditOrden] = useState(0);
  const [editColor, setEditColor] = useState('gray');

  useEffect(() => {
    cargarCategorias();
  }, []);

  useEffect(() => {
    if (categoriaActiva) {
      cargarOpciones(categoriaActiva);
    }
  }, [categoriaActiva]);

  const cargarCategorias = async () => {
    try {
      const { data } = await api.get('/rma-seguimiento/opciones/categorias');
      setCategorias(data);
      if (data.length > 0 && !categoriaActiva) {
        setCategoriaActiva(data[0]);
      }
    } catch {
      setError('Error al cargar categorías');
    }
  };

  const cargarOpciones = async (categoria) => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/rma-seguimiento/opciones', {
        params: { categoria, solo_activas: false },
      });
      setOpciones(data);
    } catch {
      setError('Error al cargar opciones');
    } finally {
      setLoading(false);
    }
  };

  const crearOpcion = async () => {
    const categoriaTarget = nuevaCategoria || categoriaActiva;
    if (!nuevoValor.trim() || !categoriaTarget) return;

    setSaving(true);
    try {
      await api.post('/rma-seguimiento/opciones', {
        categoria: categoriaTarget,
        valor: nuevoValor.trim(),
        orden: nuevoOrden,
        color: nuevoColor,
      });
      setNuevoValor('');
      setNuevoOrden(0);
      setNuevoColor('gray');
      setNuevaCategoria('');
      setShowForm(false);

      // Si la categoría es nueva, recargar categorías
      if (!categorias.includes(categoriaTarget)) {
        await cargarCategorias();
        setCategoriaActiva(categoriaTarget);
      } else {
        await cargarOpciones(categoriaActiva);
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(detail || 'Error al crear opción');
    } finally {
      setSaving(false);
    }
  };

  const iniciarEdicion = (opcion) => {
    setEditandoId(opcion.id);
    setEditValor(opcion.valor);
    setEditOrden(opcion.orden);
    setEditColor(opcion.color || 'gray');
  };

  const cancelarEdicion = () => {
    setEditandoId(null);
    setEditValor('');
    setEditOrden(0);
    setEditColor('gray');
  };

  const guardarEdicion = async (opcionId) => {
    if (!editValor.trim()) return;

    try {
      await api.put(`/rma-seguimiento/opciones/${opcionId}`, {
        valor: editValor.trim(),
        orden: editOrden,
        color: editColor,
      });
      cancelarEdicion();
      await cargarOpciones(categoriaActiva);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(detail || 'Error al actualizar opción');
    }
  };

  const toggleActivo = async (opcion) => {
    try {
      await api.put(`/rma-seguimiento/opciones/${opcion.id}`, {
        activo: !opcion.activo,
      });
      await cargarOpciones(categoriaActiva);
    } catch {
      setError('Error al cambiar estado');
    }
  };

  const handleKeyDown = (e, action) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      action();
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      if (editandoId) {
        cancelarEdicion();
      } else {
        setShowForm(false);
      }
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <div className={styles.title}>
            <Settings size={20} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '8px' }} />
            Opciones de Dropdowns
          </div>
          <div className={styles.subtitle}>
            Gestioná los valores disponibles en cada dropdown del módulo RMA
          </div>
        </div>
        <button
          className="btn-tesla primary sm"
          onClick={() => setShowForm(!showForm)}
        >
          <Plus size={16} />
          Nueva opción
        </button>
      </div>

      {error && (
        <div style={{ color: 'var(--error)', marginBottom: 'var(--spacing-md)', fontSize: 'var(--font-sm)' }}>
          {error}
          <button
            onClick={() => setError(null)}
            style={{ marginLeft: '8px', background: 'none', border: 'none', color: 'var(--error)', cursor: 'pointer', textDecoration: 'underline' }}
          >
            Cerrar
          </button>
        </div>
      )}

      {/* Selector de categorías */}
      <div className={styles.categoriaSelector}>
        {categorias.map((cat) => (
          <button
            key={cat}
            className={`${styles.categoriaChip} ${categoriaActiva === cat ? styles.categoriaChipActive : ''}`}
            onClick={() => setCategoriaActiva(cat)}
          >
            {CATEGORIA_LABELS[cat] || cat}
          </button>
        ))}
      </div>

      {/* Form para nueva opción */}
      {showForm && (
        <div className={styles.formInline}>
          <div className={styles.formGroup}>
            <label>Categoría</label>
            <select
              value={nuevaCategoria || categoriaActiva || ''}
              onChange={(e) => setNuevaCategoria(e.target.value)}
            >
              {categorias.map((cat) => (
                <option key={cat} value={cat}>
                  {CATEGORIA_LABELS[cat] || cat}
                </option>
              ))}
              <option value="__nueva__">+ Nueva categoría...</option>
            </select>
          </div>

          {(nuevaCategoria === '__nueva__') && (
            <div className={styles.formGroup}>
              <label>Nombre categoría</label>
              <input
                type="text"
                value={nuevaCategoria === '__nueva__' ? '' : nuevaCategoria}
                onChange={(e) => setNuevaCategoria(e.target.value)}
                placeholder="ej: estado_garantia"
              />
            </div>
          )}

          <div className={styles.formGroup}>
            <label>Valor</label>
            <input
              type="text"
              value={nuevoValor}
              onChange={(e) => setNuevoValor(e.target.value)}
              onKeyDown={(e) => handleKeyDown(e, crearOpcion)}
              placeholder="ej: Fallado"
              autoFocus
            />
          </div>

          <div className={styles.formGroup}>
            <label>Orden</label>
            <input
              type="number"
              value={nuevoOrden}
              onChange={(e) => setNuevoOrden(parseInt(e.target.value, 10) || 0)}
              onKeyDown={(e) => handleKeyDown(e, crearOpcion)}
              className={styles.ordenInput}
            />
          </div>

          <div className={styles.formGroup}>
            <label>Color</label>
            <div className={styles.colorOptions}>
              {COLORES_DISPONIBLES.map((c) => (
                <button
                  key={c.nombre}
                  type="button"
                  className={`${styles.colorOption} ${nuevoColor === c.nombre ? styles.colorOptionSelected : ''}`}
                  style={{ backgroundColor: c.hex }}
                  onClick={() => setNuevoColor(c.nombre)}
                  title={c.nombre}
                  aria-label={`Color ${c.nombre}`}
                />
              ))}
            </div>
          </div>

          <div className={styles.formActions}>
            <button
              className="btn-tesla primary sm"
              onClick={crearOpcion}
              disabled={saving || !nuevoValor.trim()}
            >
              {saving ? 'Guardando...' : 'Agregar'}
            </button>
            <button
              className="btn-tesla ghost sm"
              onClick={() => setShowForm(false)}
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {/* Tabla de opciones */}
      {loading ? (
        <div className={styles.loading}>Cargando opciones...</div>
      ) : opciones.length === 0 ? (
        <div className={styles.emptyState}>
          <Settings size={40} />
          <p>No hay opciones en esta categoría</p>
        </div>
      ) : (
        <table className={styles.opcionesTable}>
          <thead>
            <tr>
              <th>Orden</th>
              <th>Valor</th>
              <th>Color</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {opciones
              .sort((a, b) => a.orden - b.orden)
              .map((opcion) => (
                <tr key={opcion.id}>
                  {editandoId === opcion.id ? (
                    <>
                      <td>
                        <input
                          type="number"
                          value={editOrden}
                          onChange={(e) => setEditOrden(parseInt(e.target.value, 10) || 0)}
                          onKeyDown={(e) => handleKeyDown(e, () => guardarEdicion(opcion.id))}
                          className={`${styles.inlineInput} ${styles.ordenInput}`}
                        />
                      </td>
                      <td>
                        <input
                          type="text"
                          value={editValor}
                          onChange={(e) => setEditValor(e.target.value)}
                          onKeyDown={(e) => handleKeyDown(e, () => guardarEdicion(opcion.id))}
                          className={styles.inlineInput}
                          autoFocus
                        />
                      </td>
                      <td>
                        <div className={styles.colorOptions}>
                          {COLORES_DISPONIBLES.map((c) => (
                            <button
                              key={c.nombre}
                              type="button"
                              className={`${styles.colorOption} ${editColor === c.nombre ? styles.colorOptionSelected : ''}`}
                              style={{ backgroundColor: c.hex }}
                              onClick={() => setEditColor(c.nombre)}
                              title={c.nombre}
                              aria-label={`Color ${c.nombre}`}
                            />
                          ))}
                        </div>
                      </td>
                      <td>{opcion.activo ? 'Activo' : 'Inactivo'}</td>
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            className={styles.iconBtn}
                            onClick={() => guardarEdicion(opcion.id)}
                            title="Guardar"
                            aria-label="Guardar cambios"
                          >
                            <Check size={16} />
                          </button>
                          <button
                            className={styles.iconBtn}
                            onClick={cancelarEdicion}
                            title="Cancelar"
                            aria-label="Cancelar edición"
                          >
                            <X size={16} />
                          </button>
                        </div>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{opcion.orden}</td>
                      <td className={opcion.activo ? '' : styles.estadoInactivo}>
                        {opcion.valor}
                      </td>
                      <td>
                        <span
                          className={styles.colorBadge}
                          style={{
                            backgroundColor: `${getColorHex(opcion.color)}20`,
                            color: getColorHex(opcion.color),
                          }}
                        >
                          <span
                            className={styles.colorDot}
                            style={{ backgroundColor: getColorHex(opcion.color) }}
                          />
                          {opcion.color || 'sin color'}
                        </span>
                      </td>
                      <td>
                        <span className={opcion.activo ? styles.estadoActivo : styles.estadoInactivo}>
                          {opcion.activo ? 'Activo' : 'Inactivo'}
                        </span>
                      </td>
                      <td>
                        <div className={styles.rowActions}>
                          <button
                            className={styles.iconBtn}
                            onClick={() => iniciarEdicion(opcion)}
                            title="Editar"
                            aria-label="Editar opción"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            className={styles.iconBtn}
                            onClick={() => toggleActivo(opcion)}
                            title={opcion.activo ? 'Desactivar' : 'Activar'}
                            aria-label={opcion.activo ? 'Desactivar opción' : 'Activar opción'}
                          >
                            {opcion.activo ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
                          </button>
                        </div>
                      </td>
                    </>
                  )}
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
