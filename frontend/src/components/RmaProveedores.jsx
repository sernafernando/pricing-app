/**
 * RMA Proveedores - ABM de proveedores para el modulo RMA.
 *
 * Panel togglable que muestra la lista de proveedores con busqueda,
 * edicion inline de datos extendidos (direccion, contacto, config RMA),
 * y boton de sync desde ERP.
 *
 * Requiere permiso: rma.gestionar
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Search,
  Pencil,
  Check,
  X,
  RefreshCcw,
  ChevronLeft,
  ChevronRight,
  Truck,
  Phone,
  Mail,
  MapPin,
  User,
  Clock,
  Package,
  FileText,
  ToggleLeft,
  ToggleRight,
} from 'lucide-react';
import { useDebounce } from '../hooks/useDebounce';
import api from '../services/api';
import styles from './RmaProveedores.module.css';

const PAGE_SIZE = 25;

export default function RmaProveedores() {
  const [proveedores, setProveedores] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [soloActivos, setSoloActivos] = useState(true);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(null);
  const [syncResult, setSyncResult] = useState(null);

  // Editing state
  const [editandoId, setEditandoId] = useState(null);
  const [editData, setEditData] = useState({});
  const [saving, setSaving] = useState(false);

  const debouncedSearch = useDebounce(search, 400);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const cargarProveedores = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {
        page,
        page_size: PAGE_SIZE,
        solo_activos: soloActivos,
      };
      if (debouncedSearch) params.search = debouncedSearch;
      const { data } = await api.get('/rma-proveedores', { params });
      setProveedores(data.proveedores);
      setTotal(data.total);
    } catch {
      setError('Error al cargar proveedores');
      setProveedores([]);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, soloActivos]);

  useEffect(() => {
    cargarProveedores();
  }, [cargarProveedores]);

  // Reset to page 1 when search changes
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, soloActivos]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const { data } = await api.post('/rma-proveedores/sync');
      setSyncResult(data);
      cargarProveedores();
    } catch {
      setError('Error al sincronizar desde ERP');
    } finally {
      setSyncing(false);
    }
  };

  const startEditing = (prov) => {
    setEditandoId(prov.id);
    setEditData({
      nombre: prov.nombre || '',
      cuit: prov.cuit || '',
      direccion: prov.direccion || '',
      cp: prov.cp || '',
      ciudad: prov.ciudad || '',
      provincia: prov.provincia || '',
      telefono: prov.telefono || '',
      email: prov.email || '',
      representante: prov.representante || '',
      horario: prov.horario || '',
      notas: prov.notas || '',
      unidades_minimas_rma: prov.unidades_minimas_rma ?? '',
      activo: prov.activo,
    });
  };

  const cancelEditing = () => {
    setEditandoId(null);
    setEditData({});
  };

  const handleEditChange = (field, value) => {
    setEditData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = { ...editData };
      // Convert empty strings to null for optional fields
      const optionalFields = [
        'cuit', 'direccion', 'cp', 'ciudad', 'provincia',
        'telefono', 'email', 'representante', 'horario', 'notas',
      ];
      for (const f of optionalFields) {
        if (payload[f] === '') payload[f] = null;
      }
      // Convert unidades_minimas_rma to number or null
      if (payload.unidades_minimas_rma === '' || payload.unidades_minimas_rma === null) {
        payload.unidades_minimas_rma = null;
      } else {
        payload.unidades_minimas_rma = Number(payload.unidades_minimas_rma);
      }

      await api.put(`/rma-proveedores/${editandoId}`, payload);
      setEditandoId(null);
      setEditData({});
      cargarProveedores();
    } catch {
      setError('Error al guardar proveedor');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Truck size={18} />
          <h3 className={styles.title}>Proveedores RMA</h3>
          <span className={styles.badge}>{total}</span>
        </div>
        <button
          className="btn-tesla outline-subtle-primary sm"
          onClick={handleSync}
          disabled={syncing}
          title="Sincronizar proveedores nuevos desde ERP"
          aria-label="Sincronizar proveedores desde ERP"
        >
          <RefreshCcw size={14} className={syncing ? styles.spinning : ''} />
          {syncing ? 'Sincronizando...' : 'Sync ERP'}
        </button>
      </div>

      {/* Sync result */}
      {syncResult && (
        <div className={styles.syncResult}>
          Sync completado: {syncResult.insertados} nuevos, {syncResult.actualizados} actualizados
          <button
            className={styles.dismissBtn}
            onClick={() => setSyncResult(null)}
            aria-label="Cerrar mensaje"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className={styles.errorMsg}>
          {error}
          <button
            className={styles.dismissBtn}
            onClick={() => setError(null)}
            aria-label="Cerrar error"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Filters */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={14} />
          <input
            type="text"
            placeholder="Buscar por nombre, CUIT, ciudad o representante..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <label className={styles.toggleLabel}>
          <input
            type="checkbox"
            checked={soloActivos}
            onChange={(e) => setSoloActivos(e.target.checked)}
          />
          Solo activos
        </label>
      </div>

      {/* Table */}
      <div className="table-container-tesla">
        <table className="table-tesla striped">
          <thead className="table-tesla-head">
            <tr>
              <th>Nombre</th>
              <th>CUIT</th>
              <th>Ciudad</th>
              <th>Representante</th>
              <th>Telefono</th>
              <th>Uds Min</th>
              <th>Activo</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {loading ? (
              <tr>
                <td colSpan={8} className={styles.statusCell}>Cargando...</td>
              </tr>
            ) : proveedores.length === 0 ? (
              <tr>
                <td colSpan={8} className={styles.statusCell}>
                  No se encontraron proveedores
                </td>
              </tr>
            ) : (
              proveedores.map((prov) => (
                <tr key={prov.id} className={editandoId === prov.id ? styles.editingRow : ''}>
                  <td className={styles.cellNombre}>{prov.nombre}</td>
                  <td className={styles.cellMono}>{prov.cuit || '\u2014'}</td>
                  <td>{prov.ciudad || '\u2014'}</td>
                  <td>{prov.representante || '\u2014'}</td>
                  <td className={styles.cellMono}>{prov.telefono || '\u2014'}</td>
                  <td className={styles.cellCenter}>
                    {prov.unidades_minimas_rma != null ? prov.unidades_minimas_rma : '\u2014'}
                  </td>
                  <td className={styles.cellCenter}>
                    {prov.activo ? (
                      <ToggleRight size={18} className={styles.iconActive} />
                    ) : (
                      <ToggleLeft size={18} className={styles.iconInactive} />
                    )}
                  </td>
                  <td>
                    <button
                      className="btn-tesla ghost sm"
                      onClick={() => startEditing(prov)}
                      title="Editar proveedor"
                      aria-label={`Editar ${prov.nombre}`}
                    >
                      <Pencil size={14} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            className="btn-tesla ghost sm"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            aria-label="Pagina anterior"
          >
            <ChevronLeft size={16} />
          </button>
          <span className={styles.pageInfo}>
            Pagina {page} de {totalPages} ({total} proveedores)
          </span>
          <button
            className="btn-tesla ghost sm"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            aria-label="Pagina siguiente"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Edit panel */}
      {editandoId && (
        <div className={styles.editPanel}>
          <div className={styles.editHeader}>
            <h4>Editar Proveedor</h4>
            <div className={styles.editActions}>
              <button
                className="btn-tesla outline-subtle-primary sm"
                onClick={handleSave}
                disabled={saving}
              >
                <Check size={14} />
                {saving ? 'Guardando...' : 'Guardar'}
              </button>
              <button
                className="btn-tesla ghost sm"
                onClick={cancelEditing}
                disabled={saving}
              >
                <X size={14} />
                Cancelar
              </button>
            </div>
          </div>

          <div className={styles.editGrid}>
            {/* Column 1: Identity */}
            <div className={styles.editSection}>
              <h5 className={styles.sectionTitle}>
                <FileText size={14} /> Datos base
              </h5>
              <label className={styles.fieldLabel}>
                Nombre
                <input
                  className={styles.input}
                  value={editData.nombre}
                  onChange={(e) => handleEditChange('nombre', e.target.value)}
                />
              </label>
              <label className={styles.fieldLabel}>
                CUIT
                <input
                  className={styles.input}
                  value={editData.cuit}
                  onChange={(e) => handleEditChange('cuit', e.target.value)}
                  placeholder="30-12345678-9"
                />
              </label>
              <label className={styles.fieldLabel}>
                Estado
                <div className={styles.toggleRow}>
                  <input
                    type="checkbox"
                    checked={editData.activo}
                    onChange={(e) => handleEditChange('activo', e.target.checked)}
                  />
                  <span>{editData.activo ? 'Activo' : 'Inactivo'}</span>
                </div>
              </label>
            </div>

            {/* Column 2: Address */}
            <div className={styles.editSection}>
              <h5 className={styles.sectionTitle}>
                <MapPin size={14} /> Direccion
              </h5>
              <label className={styles.fieldLabel}>
                Direccion
                <input
                  className={styles.input}
                  value={editData.direccion}
                  onChange={(e) => handleEditChange('direccion', e.target.value)}
                  placeholder="Calle y numero"
                />
              </label>
              <div className={styles.fieldRow}>
                <label className={styles.fieldLabel}>
                  Ciudad
                  <input
                    className={styles.input}
                    value={editData.ciudad}
                    onChange={(e) => handleEditChange('ciudad', e.target.value)}
                  />
                </label>
                <label className={styles.fieldLabel}>
                  CP
                  <input
                    className={styles.input}
                    value={editData.cp}
                    onChange={(e) => handleEditChange('cp', e.target.value)}
                  />
                </label>
              </div>
              <label className={styles.fieldLabel}>
                Provincia
                <input
                  className={styles.input}
                  value={editData.provincia}
                  onChange={(e) => handleEditChange('provincia', e.target.value)}
                />
              </label>
            </div>

            {/* Column 3: Contact */}
            <div className={styles.editSection}>
              <h5 className={styles.sectionTitle}>
                <User size={14} /> Contacto
              </h5>
              <label className={styles.fieldLabel}>
                Representante
                <input
                  className={styles.input}
                  value={editData.representante}
                  onChange={(e) => handleEditChange('representante', e.target.value)}
                  placeholder="Nombre del contacto"
                />
              </label>
              <label className={styles.fieldLabel}>
                Telefono
                <input
                  className={styles.input}
                  value={editData.telefono}
                  onChange={(e) => handleEditChange('telefono', e.target.value)}
                />
              </label>
              <label className={styles.fieldLabel}>
                Email
                <input
                  className={styles.input}
                  type="email"
                  value={editData.email}
                  onChange={(e) => handleEditChange('email', e.target.value)}
                />
              </label>
            </div>

            {/* Column 4: RMA Config */}
            <div className={styles.editSection}>
              <h5 className={styles.sectionTitle}>
                <Package size={14} /> Config RMA
              </h5>
              <label className={styles.fieldLabel}>
                Horario de recepcion
                <input
                  className={styles.input}
                  value={editData.horario}
                  onChange={(e) => handleEditChange('horario', e.target.value)}
                  placeholder="Lun-Vie 9-17"
                />
              </label>
              <label className={styles.fieldLabel}>
                Unidades minimas RMA
                <input
                  className={styles.input}
                  type="number"
                  min="0"
                  value={editData.unidades_minimas_rma}
                  onChange={(e) => handleEditChange('unidades_minimas_rma', e.target.value)}
                  placeholder="Minimo para enviar"
                />
              </label>
              <label className={styles.fieldLabel}>
                Notas
                <textarea
                  className={styles.textarea}
                  value={editData.notas}
                  onChange={(e) => handleEditChange('notas', e.target.value)}
                  rows={3}
                  placeholder="Notas internas sobre RMA con este proveedor..."
                />
              </label>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
