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
  // F7: permission fix — was *_proveedores by mistake (AC-F2-13)
  const canEdit = tienePermiso('administracion.gestionar_caja');

  const [bancos, setBancos] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [soloActivos, setSoloActivos] = useState(true);
  const [empresas, setEmpresas] = useState([]);

  // T3.13 — movimientos panel
  const [selectedBanco, setSelectedBanco] = useState(null);
  const [movimientos, setMovimientos] = useState([]);
  const [loadingMov, setLoadingMov] = useState(false);
  const [movPage, setMovPage] = useState(1);
  const [movTotal, setMovTotal] = useState(0);
  const MOV_PAGE_SIZE = 20;

  const fetchMovimientos = useCallback(async (bancoId, page = 1) => {
    setLoadingMov(true);
    try {
      const { data } = await api.get(
        `/administracion/bancos/${bancoId}/movimientos?page=${page}&page_size=${MOV_PAGE_SIZE}`
      );
      setMovimientos(Array.isArray(data?.items) ? data.items : []);
      setMovTotal(data?.total ?? 0);
      setMovPage(page);
    } catch {
      setMovimientos([]);
      setMovTotal(0);
    } finally {
      setLoadingMov(false);
    }
  }, []);

  const handleSelectBanco = (banco) => {
    setSelectedBanco(banco);
    fetchMovimientos(banco.id, 1);
  };

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  function emptyForm() {
    return {
      banco: '', tipo_cuenta: '', cbu: '', alias: '',
      numero_cuenta: '', sucursal: '',
      titular: '', cuit_titular: '', saldo_inicial: 0, notas: '',
      empresa_id: null,  // F7: empresa assignment (AD-13)
    };
  }

  useEffect(() => {
    api.get('/admin/empresas').then(({ data }) => setEmpresas(data)).catch(() => setEmpresas([]));
  }, []);

  // Derivar moneda del tipo de cuenta
  const getMoneda = (tipoCuenta) => {
    if (!tipoCuenta) return 'ARS';
    return tipoCuenta.includes('USD') ? 'USD' : 'ARS';
  };

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
      titular: banco.titular || '',
      cuit_titular: banco.cuit_titular || '',
      saldo_inicial: banco.saldo_inicial || 0,
      notas: banco.notas || '',
      empresa_id: banco.empresa_id ?? null,  // F7: hydrate empresa
    });
    setFormError(null);
    setShowModal(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const payload = { ...form, moneda: getMoneda(form.tipo_cuenta) };
      if (editingId) {
        await api.put(`/administracion/bancos/${editingId}`, payload);
      } else {
        await api.post('/administracion/bancos', payload);
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
        <BancosGrouped bancos={bancos} canEdit={canEdit} onEdit={handleOpenEdit} onToggle={handleToggle} onSelect={handleSelectBanco} selectedId={selectedBanco?.id} />
      )}

      {/* T3.13 — movimientos panel */}
      {selectedBanco && (
        <div className={styles.movPanel}>
          <div className={styles.movPanelHeader}>
            <div className={styles.movPanelTitle}>
              <Landmark size={16} />
              <span>Movimientos — {selectedBanco.banco}</span>
              <span className={styles.movPanelSaldo}>
                Saldo actual:{' '}
                <strong>
                  {selectedBanco.moneda === 'USD' ? 'USD ' : '$ '}
                  {Number(selectedBanco.saldo_actual ?? selectedBanco.saldo_inicial).toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                </strong>
              </span>
            </div>
            <button className={styles.btnIcon} onClick={() => setSelectedBanco(null)} title="Cerrar panel">
              <X size={16} />
            </button>
          </div>
          {loadingMov ? (
            <div className={styles.movLoading}><Loader2 size={16} className={styles.spinning} /> Cargando...</div>
          ) : movimientos.length === 0 ? (
            <div className={styles.movEmpty}>Sin movimientos registrados.</div>
          ) : (
            <>
              <table className={styles.movTable}>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Monto</th>
                    <th>Saldo post</th>
                    <th>Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {movimientos.map((m) => (
                    <tr key={m.id} className={m.tipo === 'egreso' ? styles.rowEgreso : styles.rowIngreso}>
                      <td>{m.fecha}</td>
                      <td className={styles.movTipo}>{m.tipo}</td>
                      <td className={styles.movMonto}>
                        {m.tipo === 'egreso' ? '−' : '+'}
                        {selectedBanco.moneda === 'USD' ? 'USD ' : '$ '}
                        {Number(m.monto).toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                      </td>
                      <td>
                        {selectedBanco.moneda === 'USD' ? 'USD ' : '$ '}
                        {Number(m.saldo_posterior).toLocaleString('es-AR', { minimumFractionDigits: 2 })}
                      </td>
                      <td className={styles.movDetalle}>{m.detalle}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {movTotal > MOV_PAGE_SIZE && (
                <div className={styles.movPager}>
                  <button
                    className={styles.btnSecondary}
                    disabled={movPage === 1}
                    onClick={() => fetchMovimientos(selectedBanco.id, movPage - 1)}
                  >
                    Anterior
                  </button>
                  <span>{movPage} / {Math.ceil(movTotal / MOV_PAGE_SIZE)}</span>
                  <button
                    className={styles.btnSecondary}
                    disabled={movPage >= Math.ceil(movTotal / MOV_PAGE_SIZE)}
                    onClick={() => fetchMovimientos(selectedBanco.id, movPage + 1)}
                  >
                    Siguiente
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Modal crear/editar */}
      {showModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
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
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Tipo de cuenta</label>
                <select className={styles.formInput} value={form.tipo_cuenta} onChange={(e) => setForm({ ...form, tipo_cuenta: e.target.value })}>
                  <option value="">Seleccionar</option>
                  <option value="CA $">CA $ (Caja de Ahorro Pesos)</option>
                  <option value="CC $">CC $ (Cuenta Corriente Pesos)</option>
                  <option value="CU $">CU $ (Cuenta Única Pesos)</option>
                  <option value="CA USD">CA USD (Caja de Ahorro Dólares)</option>
                  <option value="CC USD">CC USD (Cuenta Corriente Dólares)</option>
                  <option value="CU USD">CU USD (Cuenta Única Dólares)</option>
                </select>
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
                <label className={styles.formLabel}>Empresa</label>
                <select
                  className={styles.formInput}
                  value={form.empresa_id ?? ''}
                  onChange={(e) => setForm({ ...form, empresa_id: e.target.value ? parseInt(e.target.value, 10) : null })}
                >
                  <option value="">Sin asignar</option>
                  {empresas.map((emp) => (
                    <option key={emp.id} value={emp.id}>{emp.nombre}</option>
                  ))}
                </select>
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

// ── Bancos agrupados por titular/CUIT ────────────────────────────

function BancosGrouped({ bancos, canEdit, onEdit, onToggle, onSelect, selectedId }) {
  // Agrupar por cuit_titular (si no tiene, agrupar bajo "Sin titular")
  const groups = {};
  for (const b of bancos) {
    const key = b.cuit_titular || '__sin_titular__';
    if (!groups[key]) {
      groups[key] = { titular: b.titular || 'Sin titular asignado', cuit: b.cuit_titular, bancos: [] };
    }
    groups[key].bancos.push(b);
  }

  const sortedKeys = Object.keys(groups).sort((a, b) => {
    if (a === '__sin_titular__') return 1;
    if (b === '__sin_titular__') return -1;
    return (groups[a].titular || '').localeCompare(groups[b].titular || '');
  });

  return (
    <div className={styles.groupedContainer}>
      {sortedKeys.map((key) => {
        const group = groups[key];
        return (
          <div key={key} className={styles.group}>
            <div className={styles.groupHeader}>
              <span className={styles.groupTitle}>{group.titular}</span>
              {group.cuit && <span className={styles.groupCuit}>CUIT {group.cuit}</span>}
            </div>
            <div className={styles.grid}>
              {group.bancos.map((b) => (
                <BancoCard key={b.id} banco={b} canEdit={canEdit} onEdit={onEdit} onToggle={onToggle} onSelect={onSelect} isSelected={b.id === selectedId} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BancoCard({ banco: b, canEdit, onEdit, onToggle, onSelect, isSelected }) {
  const monedaPrefix = (b.moneda || b.tipo_cuenta || '').includes('USD') ? 'USD ' : '$ ';
  return (
    <div
      className={`${styles.card} ${!b.activo ? styles.cardInactive : ''} ${isSelected ? styles.cardSelected : ''}`}
      onClick={() => onSelect && onSelect(b)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onSelect && onSelect(b)}
      style={{ cursor: 'pointer' }}
    >
      <div className={styles.cardHeader}>
        <span className={styles.cardTitle}>{b.banco}</span>
        <div className={styles.cardActions}>
          {b.tipo_cuenta && <span className={styles.tag}>{b.tipo_cuenta}</span>}
          {canEdit && (
            <>
              <button className={styles.btnIcon} onClick={(e) => { e.stopPropagation(); onEdit(b); }} title="Editar">
                <Pencil size={14} />
              </button>
              <button className={styles.btnIcon} onClick={(e) => { e.stopPropagation(); onToggle(b); }} title={b.activo ? 'Deshabilitar' : 'Habilitar'}>
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
        <div className={styles.fieldRow}>
          <span className={styles.fieldLabel}>Saldo inicial</span>
          <span className={styles.fieldValue}>
            {monedaPrefix}{Number(b.saldo_inicial).toLocaleString('es-AR', { minimumFractionDigits: 2 })}
          </span>
        </div>
        {b.saldo_actual != null && (
          <div className={styles.fieldRow}>
            <span className={styles.fieldLabel}>Saldo actual</span>
            <span className={`${styles.fieldValue} ${styles.saldoActual}`}>
              {monedaPrefix}{Number(b.saldo_actual).toLocaleString('es-AR', { minimumFractionDigits: 2 })}
            </span>
          </div>
        )}
        {b.notas && <div className={styles.fieldRow}><span className={styles.fieldLabel}>Notas</span><span className={styles.fieldValue}>{b.notas}</span></div>}
      </div>
    </div>
  );
}
