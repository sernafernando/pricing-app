import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './AdministracionImpuestos.module.css';
import { registrarPagina } from '../registry/tabRegistry';
import {
  Receipt,
  Plus,
  AlertCircle,
  Loader2,
  X,
  Pencil,
  EyeOff,
  Eye,
} from 'lucide-react';

registrarPagina({
  pagePath: '/administracion/impuestos',
  pageLabel: 'Administración - Impuestos',
  tabs: [],
});

const TIPOS = [
  { value: 'iva', label: 'IVA' },
  { value: 'retencion', label: 'Retención' },
  { value: 'percepcion', label: 'Percepción' },
  { value: 'otro', label: 'Otro' },
];

const TIPO_LABELS = Object.fromEntries(TIPOS.map((t) => [t.value, t.label]));

const APLICA_OPTIONS = [
  { value: 'ambos', label: 'Ambos' },
  { value: 'compras', label: 'Compras' },
  { value: 'ventas', label: 'Ventas' },
];

export default function AdministracionImpuestos() {
  const { tienePermiso } = usePermisos();
  const canEdit = tienePermiso('administracion.gestionar_proveedores');

  const [impuestos, setImpuestos] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [soloActivos, setSoloActivos] = useState(true);
  const [filtroTipo, setFiltroTipo] = useState('');

  // Modal
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  function emptyForm() {
    return {
      nombre: '', tipo: 'iva', codigo_afip: '',
      alicuota: '', alicuota_no_inscripto: '', alicuota_convenio: '',
      segun_padron: false, jurisdiccion: '',
      base_imponible_minima: '', percepcion_minima: '', minimo_incluye_iva: false,
      aplica_a: 'ambos', notas: '',
    };
  }

  const showJurisdiccion = (tipo) => tipo === 'percepcion' || tipo === 'retencion';

  const fetchImpuestos = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ solo_activos: String(soloActivos) });
      if (filtroTipo) params.set('tipo', filtroTipo);
      const { data } = await api.get(`/administracion/impuestos?${params}`);
      setImpuestos(data.impuestos);
      setTotal(data.total);
    } catch {
      setImpuestos([]);
    } finally {
      setLoading(false);
    }
  }, [soloActivos, filtroTipo]);

  useEffect(() => { fetchImpuestos(); }, [fetchImpuestos]);

  const handleOpenCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setFormError(null);
    setShowModal(true);
  };

  const handleOpenEdit = (imp) => {
    setEditingId(imp.id);
    setForm({
      nombre: imp.nombre || '',
      tipo: imp.tipo || 'iva',
      codigo_afip: imp.codigo_afip ?? '',
      alicuota: imp.alicuota ?? '',
      alicuota_no_inscripto: imp.alicuota_no_inscripto ?? '',
      alicuota_convenio: imp.alicuota_convenio ?? '',
      segun_padron: imp.segun_padron || false,
      jurisdiccion: imp.jurisdiccion || '',
      base_imponible_minima: imp.base_imponible_minima ?? '',
      percepcion_minima: imp.percepcion_minima ?? '',
      minimo_incluye_iva: imp.minimo_incluye_iva || false,
      aplica_a: imp.aplica_a || 'ambos',
      notas: imp.notas || '',
    });
    setFormError(null);
    setShowModal(true);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const optNum = (v) => v === '' || v === null || v === undefined ? null : parseFloat(v);
      const payload = {
        ...form,
        alicuota: parseFloat(form.alicuota) || 0,
        alicuota_no_inscripto: optNum(form.alicuota_no_inscripto),
        alicuota_convenio: optNum(form.alicuota_convenio),
        codigo_afip: form.codigo_afip ? parseInt(form.codigo_afip, 10) : null,
        jurisdiccion: form.jurisdiccion || null,
        base_imponible_minima: optNum(form.base_imponible_minima),
        percepcion_minima: optNum(form.percepcion_minima),
      };
      if (editingId) {
        await api.put(`/administracion/impuestos/${editingId}`, payload);
      } else {
        await api.post('/administracion/impuestos', payload);
      }
      setShowModal(false);
      fetchImpuestos();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error guardando');
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (imp) => {
    await api.put(`/administracion/impuestos/${imp.id}`, { activo: !imp.activo });
    fetchImpuestos();
  };

  // Agrupar por tipo
  const grouped = {};
  for (const imp of impuestos) {
    const key = imp.tipo;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(imp);
  }
  const tipoOrder = ['iva', 'retencion', 'percepcion', 'otro'];
  const sortedTypes = tipoOrder.filter((t) => grouped[t]);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Receipt size={28} />
          <h1 className={styles.title}>Impuestos</h1>
          <span className={styles.badge}>{total}</span>
        </div>
        <div className={styles.headerActions}>
          <select
            className={styles.filterSelect}
            value={filtroTipo}
            onChange={(e) => setFiltroTipo(e.target.value)}
          >
            <option value="">Todos los tipos</option>
            {TIPOS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
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
              <Plus size={16} /> Nuevo
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className={styles.loadingState}>
          <Loader2 size={24} className={styles.spinning} />
          Cargando...
        </div>
      ) : impuestos.length === 0 ? (
        <div className={styles.emptyState}>No se encontraron impuestos</div>
      ) : (
        <div className={styles.groupedContainer}>
          {sortedTypes.map((tipo) => (
            <div key={tipo} className={styles.group}>
              <h2 className={styles.groupTitle}>{TIPO_LABELS[tipo] || tipo}</h2>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Nombre</th>
                    <th>Jurisdicción</th>
                    <th>Alícuota</th>
                    <th>No Inscr.</th>
                    <th>Conv. ML</th>
                    <th>Mínimos</th>
                    <th>Aplica a</th>
                    {canEdit && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {grouped[tipo].map((imp) => (
                    <tr key={imp.id} className={!imp.activo ? styles.rowInactive : ''}>
                      <td className={styles.cellName}>
                        {imp.nombre}
                        {imp.segun_padron && <span className={styles.tagPadron}>Según padrón</span>}
                      </td>
                      <td className={styles.cellJurisdiccion}>{imp.jurisdiccion || '—'}</td>
                      <td className={styles.cellAlicuota}>{imp.segun_padron && Number(imp.alicuota) === 0 ? 'Padrón' : `${Number(imp.alicuota).toFixed(2)}%`}</td>
                      <td className={styles.cellAlicuota}>{imp.alicuota_no_inscripto != null ? `${Number(imp.alicuota_no_inscripto).toFixed(2)}%` : '—'}</td>
                      <td className={styles.cellAlicuota}>{imp.alicuota_convenio != null && Number(imp.alicuota_convenio) > 0 ? `${Number(imp.alicuota_convenio).toFixed(2)}%` : '—'}</td>
                      <td className={styles.cellMinimos}>
                        {imp.base_imponible_minima != null && (
                          <span>Base: ${Number(imp.base_imponible_minima).toLocaleString('es-AR')}{imp.minimo_incluye_iva ? ' +IVA' : ''}</span>
                        )}
                        {imp.percepcion_minima != null && (
                          <span>Perc. mín: ${Number(imp.percepcion_minima).toLocaleString('es-AR')}</span>
                        )}
                        {imp.base_imponible_minima == null && imp.percepcion_minima == null && '—'}
                      </td>
                      <td className={styles.cellAplica}>{imp.aplica_a}</td>
                      {canEdit && (
                        <td className={styles.cellActions}>
                          <button className={styles.btnIcon} onClick={() => handleOpenEdit(imp)} title="Editar">
                            <Pencil size={14} />
                          </button>
                          <button className={styles.btnIcon} onClick={() => handleToggle(imp)} title={imp.activo ? 'Deshabilitar' : 'Habilitar'}>
                            {imp.activo ? <EyeOff size={14} /> : <Eye size={14} />}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {/* Modal crear/editar */}
      {showModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>{editingId ? 'Editar Impuesto' : 'Nuevo Impuesto'}</h2>
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
                <label className={styles.formLabel}>Nombre *</label>
                <input className={styles.formInput} value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} required autoFocus />
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Tipo *</label>
                  <select className={styles.formInput} value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
                    {TIPOS.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Alícuota (%) *</label>
                  <input className={styles.formInput} type="number" step="0.0001" min="0" max="100" value={form.alicuota} onChange={(e) => setForm({ ...form, alicuota: e.target.value })} required />
                </div>
              </div>
              {showJurisdiccion(form.tipo) && (
                <>
                  <div className={styles.formRow}>
                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Jurisdicción</label>
                      <input className={styles.formInput} value={form.jurisdiccion} onChange={(e) => setForm({ ...form, jurisdiccion: e.target.value })} placeholder="Ej: Buenos Aires, CABA" />
                    </div>
                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Alícuota no inscripto (%)</label>
                      <input className={styles.formInput} type="number" step="0.0001" min="0" max="100" value={form.alicuota_no_inscripto} onChange={(e) => setForm({ ...form, alicuota_no_inscripto: e.target.value })} />
                    </div>
                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Alícuota conv. multilateral (%)</label>
                      <input className={styles.formInput} type="number" step="0.0001" min="0" max="100" value={form.alicuota_convenio} onChange={(e) => setForm({ ...form, alicuota_convenio: e.target.value })} />
                    </div>
                  </div>
                  <div className={styles.formRow}>
                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Base imponible mínima ($)</label>
                      <input className={styles.formInput} type="number" step="0.01" min="0" value={form.base_imponible_minima} onChange={(e) => setForm({ ...form, base_imponible_minima: e.target.value })} />
                    </div>
                    <div className={styles.formGroup}>
                      <label className={styles.formLabel}>Percepción mínima ($)</label>
                      <input className={styles.formInput} type="number" step="0.01" min="0" value={form.percepcion_minima} onChange={(e) => setForm({ ...form, percepcion_minima: e.target.value })} />
                    </div>
                  </div>
                  <div className={styles.formRow}>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={form.segun_padron} onChange={(e) => setForm({ ...form, segun_padron: e.target.checked })} />
                      Alícuota según padrón
                    </label>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={form.minimo_incluye_iva} onChange={(e) => setForm({ ...form, minimo_incluye_iva: e.target.checked })} />
                      Mínimo incluye IVA
                    </label>
                  </div>
                </>
              )}
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Código AFIP</label>
                  <input className={styles.formInput} type="number" value={form.codigo_afip} onChange={(e) => setForm({ ...form, codigo_afip: e.target.value })} placeholder="Opcional" />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Aplica a</label>
                  <select className={styles.formInput} value={form.aplica_a} onChange={(e) => setForm({ ...form, aplica_a: e.target.value })}>
                    {APLICA_OPTIONS.map((a) => (
                      <option key={a.value} value={a.value}>{a.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Notas</label>
                <textarea className={styles.formTextarea} value={form.notas} onChange={(e) => setForm({ ...form, notas: e.target.value })} rows={2} />
              </div>
              <div className={styles.modalActions}>
                <button type="button" className={styles.btnSecondary} onClick={() => setShowModal(false)}>Cancelar</button>
                <button type="submit" className={styles.btnPrimary} disabled={saving}>{saving ? 'Guardando...' : (editingId ? 'Guardar' : 'Crear')}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
