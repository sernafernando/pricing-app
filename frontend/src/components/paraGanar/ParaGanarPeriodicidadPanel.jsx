import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import { useTiendasOficiales } from '../../hooks/useTiendasOficiales';
import ParaGanarPeriodicidadDetail from './ParaGanarPeriodicidadDetail';
import ParaGanarPeriodicidadList from './ParaGanarPeriodicidadList';
import {
  EMPTY_PERIODICIDAD_FORM,
  formToPeriodicidadPayload,
  subscriptionToForm,
} from './periodicidadForm';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarPeriodicidadPanel() {
  const { tienePermiso } = usePermisos();
  const canView = tienePermiso('productos.ver');
  const canWrite = tienePermiso('productos.editar_precios');
  const { grupos: tiendasGrupos, getLabel } = useTiendasOficiales();

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState(null);

  const [selectedEan, setSelectedEan] = useState(null);
  const [draftEan, setDraftEan] = useState('');
  const [form, setForm] = useState(EMPTY_PERIODICIDAD_FORM);
  const [isNew, setIsNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [formOk, setFormOk] = useState(false);
  const [pricelists, setPricelists] = useState([]);

  const pageSize = 50;
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);

  const loadList = useCallback(async () => {
    if (!canView) return;
    setLoading(true);
    setListError(null);
    try {
      const { data } = await api.get('/para-ganar/periodicidad', {
        params: { page, page_size: pageSize, ...(q ? { q } : {}) },
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      setItems([]);
      setTotal(0);
      if (err.response?.status === 403) {
        setListError('No tenés permiso para ver periodicidad (productos.ver).');
      } else {
        setListError('No se pudo cargar la lista de suscripciones.');
      }
    } finally {
      setLoading(false);
    }
  }, [canView, page, q]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    let cancelled = false;
    async function loadPricelists() {
      try {
        const { data } = await api.get('/para-ganar/alcance-opciones');
        if (!cancelled) setPricelists(data.listas_precios || []);
      } catch {
        if (!cancelled) setPricelists([]);
      }
    }
    if (canView) loadPricelists();
    return () => {
      cancelled = true;
    };
  }, [canView]);

  const openSubscription = (row) => {
    setSelectedEan(row.ean);
    setDraftEan(row.ean);
    setForm(subscriptionToForm(row));
    setIsNew(false);
    setFormError(null);
    setFormOk(false);
  };

  const startNew = () => {
    const ean = draftEan.trim();
    if (!ean) {
      setFormError('Ingresá un EAN para suscribir.');
      return;
    }
    const existing = items.find((row) => row.ean === ean);
    if (existing) {
      openSubscription(existing);
      return;
    }
    setSelectedEan(ean);
    setForm({ ...EMPTY_PERIODICIDAD_FORM });
    setIsNew(true);
    setFormError(null);
    setFormOk(false);
  };

  const handleSave = async () => {
    if (!selectedEan || !canWrite) return;
    const built = formToPeriodicidadPayload(form);
    if (!built.ok) {
      setFormError(built.error);
      setFormOk(false);
      return;
    }
    setSaving(true);
    setFormError(null);
    setFormOk(false);
    try {
      const { data } = await api.put(
        `/para-ganar/periodicidad/${encodeURIComponent(selectedEan)}`,
        built.payload,
      );
      setForm(subscriptionToForm(data));
      setIsNew(false);
      setFormOk(true);
      await loadList();
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (err.response?.status === 403) {
        setFormError('No tenés permiso para guardar (productos.editar_precios).');
      } else if (typeof detail === 'string') {
        setFormError(detail);
      } else {
        setFormError('No se pudo guardar la suscripción.');
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedEan || !canWrite || isNew) return;
    setDeleting(true);
    setFormError(null);
    setFormOk(false);
    try {
      await api.delete(`/para-ganar/periodicidad/${encodeURIComponent(selectedEan)}`);
      setSelectedEan(null);
      setForm(EMPTY_PERIODICIDAD_FORM);
      setIsNew(false);
      await loadList();
    } catch (err) {
      if (err.response?.status === 403) {
        setFormError('No tenés permiso para borrar (productos.editar_precios).');
      } else {
        setFormError('No se pudo quitar la suscripción.');
      }
    } finally {
      setDeleting(false);
    }
  };

  if (!canView) {
    return (
      <section className={styles.periodicidadShell} aria-label="Gestionar periodicidad">
        <p className={styles.emptyBody} role="status">
          Requiere permiso productos.ver.
        </p>
      </section>
    );
  }

  return (
    <div className={styles.periodicidadRoot}>
      <section className={styles.toolbar} aria-label="Alta de EAN">
        <form
          className={styles.searchForm}
          onSubmit={(event) => {
            event.preventDefault();
            startNew();
          }}
        >
          <input
            className={styles.searchInput}
            type="search"
            value={draftEan}
            onChange={(e) => setDraftEan(e.target.value)}
            placeholder="EAN a suscribir o abrir"
            aria-label="EAN"
          />
          <button type="submit" className={styles.bulkBtn} disabled={!draftEan.trim()}>
            Abrir / suscribir
          </button>
        </form>
        <form
          className={styles.searchForm}
          onSubmit={(event) => {
            event.preventDefault();
            setPage(1);
            setQ(qInput.trim());
          }}
        >
          <input
            className={styles.searchInput}
            type="search"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
            placeholder="Filtrar lista por EAN"
            aria-label="Filtrar suscripciones"
          />
          <button type="submit" className={styles.searchBtn}>
            Buscar
          </button>
        </form>
        <span className={styles.toolbarHint}>
          {total.toLocaleString('es-AR')} suscripción{total === 1 ? '' : 'es'}
        </span>
      </section>

      <div className={styles.layout}>
        <ParaGanarPeriodicidadList
          items={items}
          loading={loading}
          error={listError}
          page={page}
          totalPages={totalPages}
          selectedEan={selectedEan}
          onSelect={openSubscription}
          onRetry={loadList}
          onPrevPage={() => setPage((p) => Math.max(1, p - 1))}
          onNextPage={() => setPage((p) => p + 1)}
        />
        <ParaGanarPeriodicidadDetail
          selectedEan={selectedEan}
          isNew={isNew}
          form={form}
          setForm={setForm}
          canWrite={canWrite}
          saving={saving}
          deleting={deleting}
          formError={formError}
          formOk={formOk}
          pricelists={pricelists}
          tiendasGrupos={tiendasGrupos}
          getLabel={getLabel}
          onSave={handleSave}
          onDelete={handleDelete}
        />
      </div>
    </div>
  );
}
