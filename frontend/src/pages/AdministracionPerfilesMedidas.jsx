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
import { Plus, Trash2 } from 'lucide-react';
import PerfilesTable from '../components/perfiles-medidas/PerfilesTable';
import PerfilForm from '../components/perfiles-medidas/PerfilForm';
import PerfilDeleteDialog from '../components/perfiles-medidas/PerfilDeleteDialog';
import { MEASUREMENT_FIELDS } from '../components/perfiles-medidas/perfilesMedidasHelpers';

registrarPagina({
  pagePath: '/perfiles-medidas',
  pageLabel: 'Administración - Perfiles de medidas',
  tabs: [],
});

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
  const [deleteError, setDeleteError] = useState(null);
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
    setDeleteError(null);
    try {
      await api.delete(`/tn-measurement-profiles/${deleteTarget.id}`);
      setDeleteTarget(null);
      fetchProfiles();
    } catch (err) {
      // El diálogo queda abierto para reintentar, pero DICIENDO qué pasó:
      // tragarse el error dejaba al operador clickeando un botón que no
      // hacía nada visible.
      setDeleteError(
        err?.response?.data?.error?.message || err?.message || 'No se pudo borrar el perfil'
      );
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
            <Plus size={15} strokeWidth={2} /> Nuevo perfil
          </button>
        )}
      </div>

      <PerfilesTable
        profiles={profiles}
        loading={loading}
        loadError={loadError}
        canEdit={canEdit}
        onCreate={handleOpenCreate}
        onEdit={handleOpenEdit}
        onDelete={(p) => setDeleteTarget(p)}
      />

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
        <PerfilForm
          formId="perfil-medidas-form"
          form={form}
          setForm={setForm}
          errors={errors}
          touched={touched}
          setTouched={setTouched}
          formError={formError}
          onSubmit={handleSave}
        />
      </ModalTesla>

      <ModalTesla
        isOpen={deleteTarget != null}
        onClose={() => { setDeleteTarget(null); setDeleteError(null); }}
        title={`Borrar "${deleteTarget?.name ?? ''}"`}
        size="sm"
        footer={
          <div className={styles.modalFooter}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={() => {
                setDeleteTarget(null);
                setDeleteError(null);
              }}
            >
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
        <PerfilDeleteDialog deleteTarget={deleteTarget} deleteError={deleteError} />
      </ModalTesla>
    </div>
  );
}
