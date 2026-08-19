/**
 * AdministracionPerfilesMedidas — admin screen for `tn_measurement_profile`
 * CRUD (PR-8). PR-4 shipped the CRUD endpoints and the
 * `admin.gestionar_tn_perfiles` permission with no screen behind it; this
 * page is that screen. Design approved by the maintainer — see the PR-8
 * brief for the exact layout spec this file follows.
 *
 * Structure mirrors `AdministracionBancos.jsx`: local list state, a
 * `ModalTesla`-hosted create/edit form, and a separate delete-confirmation
 * modal with two distinct states (in-use vs not-in-use) driven by
 * `categorias_en_uso`/`categorias_afectadas`/`total_categorias_afectadas`
 * (PR-8 gap C/D on the backend).
 */
import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla from '../components/ModalTesla';
import styles from './AdministracionPerfilesMedidas.module.css';
import { registrarPagina } from '../registry/tabRegistry';
import { Plus, Pencil, AlertTriangle, Trash2, Info, Package, Loader2 } from 'lucide-react';

registrarPagina({
  pagePath: '/perfiles-medidas',
  pageLabel: 'Administración - Perfiles de medidas',
  tabs: [],
});

const MEASUREMENT_FIELDS = [
  { key: 'weight', label: 'Peso', unit: 'kg' },
  { key: 'width', label: 'Ancho', unit: 'cm' },
  { key: 'height', label: 'Alto', unit: 'cm' },
  { key: 'depth', label: 'Profundidad', unit: 'cm' },
];

function emptyForm() {
  return { name: '', weight: '', width: '', height: '', depth: '' };
}

function validate(form) {
  const errors = {};
  MEASUREMENT_FIELDS.forEach(({ key }) => {
    const raw = form[key];
    const n = Number(raw);
    if (raw === '' || raw == null || Number.isNaN(n) || n <= 0) {
      errors[key] = 'Tiene que ser mayor a cero: Tienda Nube rechaza una caja con un lado en cero.';
    }
  });
  return errors;
}

export default function AdministracionPerfilesMedidas() {
  const { tienePermiso } = usePermisos();
  const canEdit = tienePermiso('admin.gestionar_tn_perfiles');

  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);
  const [touched, setTouched] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const { data } = await api.get('/tn-measurement-profiles');
      setProfiles(Array.isArray(data) ? data : []);
    } catch (err) {
      setProfiles([]);
      setLoadError(err?.response?.data?.error?.message || err?.message || 'No se pudieron cargar los perfiles');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfiles();
  }, [fetchProfiles]);

  const handleOpenCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setFormError(null);
    setTouched(false);
    setShowModal(true);
  };

  const handleOpenEdit = (profile) => {
    setEditingId(profile.id);
    setForm({
      name: profile.name || '',
      weight: String(profile.weight ?? ''),
      width: String(profile.width ?? ''),
      height: String(profile.height ?? ''),
      depth: String(profile.depth ?? ''),
    });
    setFormError(null);
    setTouched(false);
    setShowModal(true);
  };

  const errors = validate(form);
  const isValid = Object.keys(errors).length === 0 && form.name.trim().length > 0;

  const handleSave = async (e) => {
    e.preventDefault();
    setTouched(true);
    if (!isValid) return;
    setSaving(true);
    setFormError(null);
    try {
      const payload = {
        name: form.name.trim(),
        weight: Number(form.weight),
        width: Number(form.width),
        height: Number(form.height),
        depth: Number(form.depth),
      };
      if (editingId) {
        await api.put(`/tn-measurement-profiles/${editingId}`, payload);
      } else {
        await api.post('/tn-measurement-profiles', payload);
      }
      setShowModal(false);
      fetchProfiles();
    } catch (err) {
      setFormError(err?.response?.data?.error?.message || err?.response?.data?.detail || 'Error al guardar el perfil');
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/tn-measurement-profiles/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchProfiles();
    } catch {
      // best-effort UX: keep the dialog open so the operator can retry
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <h1 className={styles.title}>Perfiles de medidas</h1>
          <p className={styles.description}>
            Cajas reutilizables. Cuando un producto no trae medidas del ERP, elegís un perfil en vez de tipear los
            cuatro valores.
          </p>
        </div>
        {canEdit && (
          <button className={styles.btnPrimary} onClick={handleOpenCreate}>
            <PlusIcon /> Nuevo perfil
          </button>
        )}
      </div>

      <div className={styles.card}>
        {loading ? (
          <div className={styles.emptyState}>
            <Loader2 size={24} className="spinning" />
            Cargando perfiles...
          </div>
        ) : loadError ? (
          <div className={styles.emptyState}>{loadError}</div>
        ) : profiles.length === 0 ? (
          <div className={styles.emptyState}>
            <Package size={44} strokeWidth={1.5} />
            <h2 className={styles.emptyHeading}>Todavía no hay perfiles</h2>
            <p className={styles.emptyBody}>
              Un perfil guarda peso y dimensiones de una caja que usás seguido. Con perfiles cargados, publicar un
              producto sin medidas es un clic en vez de cuatro campos.
            </p>
            {canEdit && (
              <button className={styles.btnPrimary} onClick={handleOpenCreate}>
                <PlusIcon /> Crear el primero
              </button>
            )}
          </div>
        ) : (
          <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Perfil</th>
                  <th className={styles.thNum}>Peso</th>
                  <th className={styles.thNum}>Ancho</th>
                  <th className={styles.thNum}>Alto</th>
                  <th className={styles.thNum}>Prof.</th>
                  <th>Se usa en</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.id}>
                    <td className={styles.colNombre}>{p.name}</td>
                    <td className={styles.colNum}>{p.weight}</td>
                    <td className={styles.colNum}>{p.width}</td>
                    <td className={styles.colNum}>{p.height}</td>
                    <td className={styles.colNum}>{p.depth}</td>
                    <td>
                      {(p.categorias_en_uso ?? 0) === 0 ? (
                        <span className={styles.usoNone}>Sin uso</span>
                      ) : (
                        <span className={styles.usoPill}>
                          {p.categorias_en_uso} {p.categorias_en_uso === 1 ? 'categoría' : 'categorías'}
                        </span>
                      )}
                    </td>
                    {canEdit && (
                      <td className={styles.colActions}>
                        <button className={styles.btnGhostEdit} onClick={() => handleOpenEdit(p)}>
                          <Pencil size={13} /> Editar
                        </button>
                        <button className={styles.btnBorrar} onClick={() => setDeleteTarget(p)}>
                          Borrar
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className={styles.footerNote}>
              "Se usa en" cuenta las categorías que ya publicaron con ese perfil — es lo que alimenta la sugerencia
              al abrir el publicador.
            </div>
          </>
        )}
      </div>

      <ModalTesla
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        title={editingId ? 'Editar perfil' : 'Nuevo perfil'}
        size="md"
        footer={
          <div className={styles.modalFooter}>
            <button type="button" className={styles.btnSecondary} onClick={() => setShowModal(false)}>
              Cancelar
            </button>
            <button
              type="submit"
              form="perfil-medidas-form"
              className={styles.btnPrimary}
              disabled={saving || !isValid}
            >
              {saving ? 'Guardando...' : 'Guardar perfil'}
            </button>
          </div>
        }
      >
        <form id="perfil-medidas-form" onSubmit={handleSave}>
          {formError && (
            <div className={styles.alertError}>
              <AlertTriangle size={16} /> {formError}
            </div>
          )}
          <div className={styles.formGroup}>
            <label className={styles.formLabel} htmlFor="perfil-nombre">
              Nombre
            </label>
            <input
              id="perfil-nombre"
              className={styles.formInput}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              autoFocus
            />
            <span className={styles.formHint}>
              Poné las medidas en el nombre: es lo único que vas a ver al elegir el perfil desde el publicador.
            </span>
          </div>

          <h3 className={styles.groupHeading}>Medidas de la caja</h3>
          <div className={styles.formGrid}>
            {MEASUREMENT_FIELDS.map(({ key, label, unit }) => (
              <div className={styles.formGroup} key={key}>
                <label className={styles.formLabel} htmlFor={`perfil-${key}`}>
                  {label}
                </label>
                <div className={styles.numericFieldWrap}>
                  <input
                    id={`perfil-${key}`}
                    className={`${styles.formInput} ${styles.numericInput}`}
                    type="number"
                    step="0.01"
                    value={form[key]}
                    onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                    onBlur={() => setTouched(true)}
                  />
                  <span className={styles.unitSuffix}>{unit}</span>
                </div>
                {touched && errors[key] && <span className={styles.fieldError}>{errors[key]}</span>}
              </div>
            ))}
          </div>

          <div className={styles.infoNote}>
            <Info size={16} />
            <span>
              Editar un perfil no cambia lo ya publicado. Solo afecta las publicaciones que se hagan de acá en
              adelante.
            </span>
          </div>
        </form>
      </ModalTesla>

      <ModalTesla
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        title={`Borrar "${deleteTarget?.name ?? ''}"`}
        size="sm"
        footer={
          <div className={styles.modalFooter}>
            <button type="button" className={styles.btnSecondary} onClick={() => setDeleteTarget(null)}>
              Cancelar
            </button>
            <button
              type="button"
              className={styles.btnRedPrimary}
              onClick={handleConfirmDelete}
              disabled={deleting}
            >
              <Trash2 size={14} /> Borrar perfil
            </button>
          </div>
        }
      >
        {deleteTarget && (deleteTarget.categorias_en_uso ?? 0) > 0 ? (
          <>
            <div className={styles.deleteIconWrap}>
              <div className={styles.deleteIconAmber}>
                <AlertTriangle size={22} />
              </div>
            </div>
            <p className={styles.deleteBody}>
              Este perfil se viene usando en <strong>{deleteTarget.categorias_en_uso} categorías</strong>. Si lo
              borrás, esas categorías dejan de sugerir medidas y el operador va a tener que cargarlas a mano en cada
              publicación.
            </p>
            <div className={styles.affectedBlock}>
              {(deleteTarget.categorias_afectadas || []).map((cat) => (
                <span className={styles.chip} key={cat}>
                  {cat}
                </span>
              ))}
              {deleteTarget.total_categorias_afectadas > (deleteTarget.categorias_afectadas || []).length && (
                <span className={styles.chipMore}>
                  y {deleteTarget.total_categorias_afectadas - (deleteTarget.categorias_afectadas || []).length} más
                </span>
              )}
            </div>
            <p className={styles.deleteClosingLine}>
              Lo ya publicado en Tienda Nube no se toca: conserva las medidas con las que salió.
            </p>
          </>
        ) : (
          <>
            <div className={styles.deleteIconWrap}>
              <div className={styles.deleteIconRed}>
                <Trash2 size={22} />
              </div>
            </div>
            <p className={styles.deleteBody}>Ninguna categoría lo está usando. Se borra sin consecuencias.</p>
          </>
        )}
      </ModalTesla>
    </div>
  );
}

function PlusIcon() {
  return <Plus size={15} strokeWidth={2} />;
}
