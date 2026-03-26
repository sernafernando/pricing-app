import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './AdministracionBancos.module.css';
import { registrarPagina } from '../registry/tabRegistry';
import {
  Landmark,
  Plus,
  AlertCircle,
  Loader2,
  X,
  Pencil,
  EyeOff,
  Eye,
} from 'lucide-react';

registrarPagina({
  pagePath: '/administracion/bancos',
  pageLabel: 'Administración - Bancos',
  tabs: [],
});

export default function AdministracionBancos() {
  const { tienePermiso } = usePermisos();
  const canEdit = tienePermiso('administracion.gestionar_proveedores');

  const [bancos, setBancos] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [soloActivos, setSoloActivos] = useState(true);

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  function emptyForm() {
    return {
      banco: '', tipo_cuenta: '', cbu: '', alias: '',
      numero_cuenta: '', sucursal: '', moneda: 'ARS',
      titular: '', cuit_titular: '', saldo_inicial: 0, notas: '',
    };
  }

  const fetchBancos = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/administracion/bancos?solo_activos=${soloActivos}`);
      setBancos(data.bancos);
      setTotal(data.total);
    } catch {
      setBancos([]);
    } finally {
      setLoading(false);
    }
  }, [soloActivos]);

  useEffect(() => { fetchBancos(); }, [fetchBancos]);

  const handleOpenCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setFormError(null);
    setShowModal(true);
  };

  const handleOpenEdit = (banco) => {
    setEditingId(banco.id);
    setForm({
      banco: banco.banco || '',
      tipo_cuenta: banco.tipo_cuenta || '',
      cbu: banco.cbu || '',
      alias: banco.alias || '',
      numero_cuenta: banco.numero_cuenta || '',
      sucursal: banco.sucursal || '',
      moneda: banco.moneda || 'ARS',
      titular: banco.titular || '',
      cuit_titular: banco.cuit_titular || '',
      saldo_inicial: banco.saldo_inicial || 0,
      notas: banco.notas || '',
    });
    setFormError(null);
    setShowModal(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      if (editingId) {
        await api.put(`/administracion/bancos/${editingId}`, form);
      } else {
        await api.post('/administracion/bancos', form);
      }
      setShowModal(false);
      fetchBancos();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error guardando');
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (banco) => {
    await api.put(`/administracion/bancos/${banco.id}`, { activo: !banco.activo });
    fetchBancos();
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Landmark size={28} />
          <h1 className={styles.title}>Bancos</h1>
          <span className={styles.badge}>{total}</span>
        </div>
        <div className={styles.headerActions}>
          <label className={styles.checkLabel}>
            <input
              type="checkbox"
              checked={soloActivos}
              onChange={(e) => setSoloActivos(e.target.checked)}
            />
            Solo activos
          </label>
          {canEdit && (
            <button className={styles.btnPrimary} onClick={handleOpenCreate}>
              <Plus size={16} /> Nueva Cuenta
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className={styles.loadingState}>
          <Loader2 size={24} className={styles.spinning} />
          Cargando bancos...
        </div>
      ) : bancos.length === 0 ? (
        <div className={styles.emptyState}>No se encontraron cuentas bancarias</div>
      ) : (
        <div className={styles.grid}>
          {bancos.map((b) => (
            <div key={b.id} className={`${styles.card} ${!b.activo ? styles.cardInactive : ''}`}>
              <div className={styles.cardHeader}>
                <span className={styles.cardTitle}>{b.banco}</span>
                <div className={styles.cardActions}>
                  {b.tipo_cuenta && <span className={styles.tag}>{b.tipo_cuenta}</span>}
                  <span className={styles.tagMoneda}>{b.moneda}</span>
                  {canEdit && (
                    <>
                      <button className={styles.btnIcon} onClick={() => handleOpenEdit(b)} title="Editar">
                        <Pencil size={14} />
                      </button>
                      <button className={styles.btnIcon} onClick={() => handleToggle(b)} title={b.activo ? 'Deshabilitar' : 'Habilitar'}>
                        {b.activo ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className={styles.cardBody}>
                {b.cbu && <div className={styles.fieldRow}><span className={styles.fieldLabel}>CBU</span><span className={styles.fieldValue}>{b.cbu}</span></div>}
                {b.alias && <div className={styles.fieldRow}><span className={styles.fieldLabel}>Alias</span><span className={styles.fieldValue}>{b.alias}</span></div>}
                {b.numero_cuenta && <div className={styles.fieldRow}><span className={styles.fieldLabel}>Nº Cuenta</span><span className={styles.fieldValue}>{b.numero_cuenta}</span></div>}
                {b.sucursal && <div className={styles.fieldRow}><span className={styles.fieldLabel}>Sucursal</span><span className={styles.fieldValue}>{b.sucursal}</span></div>}
                {b.titular && <div className={styles.fieldRow}><span className={styles.fieldLabel}>Titular</span><span className={styles.fieldValue}>{b.titular}{b.cuit_titular ? ` (${b.cuit_titular})` : ''}</span></div>}
                <div className={styles.fieldRow}>
                  <span className={styles.fieldLabel}>Saldo inicial</span>
                  <span className={styles.fieldValue}>
                    {b.moneda === 'USD' ? 'USD ' : '$ '}{Number(b.saldo_inicial).toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                  </span>
                </div>
                {b.notas && <div className={styles.fieldRow}><span className={styles.fieldLabel}>Notas</span><span className={styles.fieldValue}>{b.notas}</span></div>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal crear/editar */}
      {showModal && (
        <div className={styles.modalOverlay} onClick={() => setShowModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>{editingId ? 'Editar Cuenta' : 'Nueva Cuenta Bancaria'}</h2>
              <button className={styles.modalClose} onClick={() => setShowModal(false)}>
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleSave} className={styles.modalBody}>
              {formError && (
                <div className={styles.alertError}>
                  <AlertCircle size={16} /> {formError}
                </div>
              )}
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Banco *</label>
                <input className={styles.formInput} value={form.banco} onChange={(e) => setForm({ ...form, banco: e.target.value })} required autoFocus />
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Tipo de cuenta</label>
                  <select className={styles.formInput} value={form.tipo_cuenta} onChange={(e) => setForm({ ...form, tipo_cuenta: e.target.value })}>
                    <option value="">Seleccionar</option>
                    <option value="CA $">CA $</option>
                    <option value="CC $">CC $</option>
                    <option value="CA USD">CA USD</option>
                    <option value="CC USD">CC USD</option>
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Moneda</label>
                  <select className={styles.formInput} value={form.moneda} onChange={(e) => setForm({ ...form, moneda: e.target.value })}>
                    <option value="ARS">ARS</option>
                    <option value="USD">USD</option>
                  </select>
                </div>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>CBU</label>
                  <input className={styles.formInput} value={form.cbu} onChange={(e) => setForm({ ...form, cbu: e.target.value })} maxLength={30} />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Alias</label>
                  <input className={styles.formInput} value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })} />
                </div>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Nº Cuenta</label>
                  <input className={styles.formInput} value={form.numero_cuenta} onChange={(e) => setForm({ ...form, numero_cuenta: e.target.value })} />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Sucursal</label>
                  <input className={styles.formInput} value={form.sucursal} onChange={(e) => setForm({ ...form, sucursal: e.target.value })} />
                </div>
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Titular</label>
                  <input className={styles.formInput} value={form.titular} onChange={(e) => setForm({ ...form, titular: e.target.value })} />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>CUIT Titular</label>
                  <input className={styles.formInput} value={form.cuit_titular} onChange={(e) => setForm({ ...form, cuit_titular: e.target.value })} />
                </div>
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Saldo inicial</label>
                <input className={styles.formInput} type="number" step="0.01" value={form.saldo_inicial} onChange={(e) => setForm({ ...form, saldo_inicial: parseFloat(e.target.value) || 0 })} />
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Notas</label>
                <textarea className={styles.formTextarea} value={form.notas} onChange={(e) => setForm({ ...form, notas: e.target.value })} rows={2} />
              </div>
              <div className={styles.modalActions}>
                <button type="button" className={styles.btnSecondary} onClick={() => setShowModal(false)}>Cancelar</button>
                <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? 'Guardando...' : (editingId ? 'Guardar' : 'Crear Cuenta')}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
