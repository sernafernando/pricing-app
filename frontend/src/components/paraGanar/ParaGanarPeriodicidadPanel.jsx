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

export default function ParaGanarPeriodicidadPanel({ scopeQueryParams = {} }) {
  const { tienePermiso } = usePermisos();
  const canView = tienePermiso('productos.ver');
  const canWrite = tienePermiso('productos.editar_precios');
  const { grupos: tiendasGrupos, getLabel } = useTiendasOficiales();

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [suscriptoFilter, setSuscriptoFilter] = useState(null); // null | true | false
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState(null);

  const [selectedEan, setSelectedEan] = useState(null);
  const [form, setForm] = useState(EMPTY_PERIODICIDAD_FORM);
  const [isNew, setIsNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [formOk, setFormOk] = useState(false);
  const [pricelists, setPricelists] = useState([]);
  const [mlaOptions, setMlaOptions] = useState([]);
  const [mlasLoading, setMlasLoading] = useState(false);

  const pageSize = 50;
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);
  // Stable key: parent rebuilds scopeQueryParams every render.
  const scopeKey = JSON.stringify(scopeQueryParams);
  // criterios_aplicados is Advisor/Criterios-only; catalog ignores it.
  const { criterios_aplicados: _criteriosOmit, ...catalogScope } = scopeQueryParams;

  const loadList = useCallback(async () => {
    if (!canView) return;
    setLoading(true);
    setListError(null);
    try {
      const { data } = await api.get('/para-ganar/periodicidad/catalogo', {
        params: {
          page,
          page_size: pageSize,
          ...catalogScope,
          ...(suscriptoFilter === true || suscriptoFilter === false
            ? { suscripto: suscriptoFilter }
            : {}),
        },
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
      setSelectedEan((prev) => {
        if (!prev) return null;
        return (data.items || []).some((row) => row.ean === prev) ? prev : null;
      });
    } catch (err) {
      setItems([]);
      setTotal(0);
      if (err.response?.status === 403) {
        setListError('No tenés permiso para ver periodicidad (productos.ver).');
      } else {
        setListError('No se pudo cargar el catálogo de EANs.');
      }
    } finally {
      setLoading(false);
    }
    // catalogScope content tracked via scopeKey
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scopeKey
  }, [canView, page, pageSize, scopeKey, suscriptoFilter]);

  useEffect(() => {
    setPage(1);
  }, [scopeKey, suscriptoFilter]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  useEffect(() => {
    let cancelled = false;
    async function loadPricelists() {
      try {
        const { data } = await api.get('/para-ganar/alcance-opciones', {
          params: catalogScope,
        });
        if (!cancelled) setPricelists(data.listas_precios || []);
      } catch {
        if (!cancelled) setPricelists([]);
      }
    }
    if (canView) loadPricelists();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scopeKey
  }, [canView, scopeKey]);

  const loadMlasForEan = useCallback(
    async (ean) => {
      if (!ean) {
        setMlaOptions([]);
        return;
      }
      setMlasLoading(true);
      try {
        const { data } = await api.get(
          `/para-ganar/periodicidad/catalogo/${encodeURIComponent(ean)}/mlas`,
          { params: catalogScope },
        );
        setMlaOptions(data.mlas || []);
      } catch {
        setMlaOptions([]);
      } finally {
        setMlasLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scopeKey
    [scopeKey],
  );

  const openEan = async (row) => {
    const ean = row.ean;
    setSelectedEan(ean);
    setFormError(null);
    setFormOk(false);
    setForm({ ...EMPTY_PERIODICIDAD_FORM });
    setIsNew(true);
    try {
      const { data } = await api.get(`/para-ganar/periodicidad/${encodeURIComponent(ean)}`);
      setForm(subscriptionToForm(data));
      setIsNew(false);
    } catch (err) {
      if (err.response?.status !== 404) {
        setFormError('No se pudo cargar la suscripción.');
      }
    }
    await loadMlasForEan(ean);
  };

  useEffect(() => {
    if (selectedEan && form.scope_mode === 'mlas') {
      loadMlasForEan(selectedEan);
    }
  }, [selectedEan, form.scope_mode, loadMlasForEan]);

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
      setForm({ ...EMPTY_PERIODICIDAD_FORM });
      setIsNew(true);
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
      <section className={styles.toolbar} aria-label="Filtro de suscripción">
        <button
          type="button"
          className={`${styles.chip} ${suscriptoFilter === null ? styles.chipActive : ''}`}
          onClick={() => setSuscriptoFilter(null)}
        >
          Todos
        </button>
        <button
          type="button"
          className={`${styles.chip} ${suscriptoFilter === true ? styles.chipActive : ''}`}
          onClick={() => setSuscriptoFilter(true)}
        >
          Suscriptos
        </button>
        <button
          type="button"
          className={`${styles.chip} ${suscriptoFilter === false ? styles.chipActive : ''}`}
          onClick={() => setSuscriptoFilter(false)}
        >
          Sin suscribir
        </button>
        <span className={styles.toolbarHint}>
          {total.toLocaleString('es-AR')} EAN{total === 1 ? '' : 's'} en alcance
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
          onSelect={openEan}
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
          mlaOptions={mlaOptions}
          mlasLoading={mlasLoading}
          onSave={handleSave}
          onDelete={handleDelete}
        />
      </div>
    </div>
  );
}
