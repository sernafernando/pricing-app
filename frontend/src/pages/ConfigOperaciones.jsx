import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Users, DollarSign, Truck, Plus, ToggleLeft, ToggleRight,
  Trash2, Save, RefreshCw, Clock, Hash, ChevronDown, Building,
} from 'lucide-react';
import api from '../services/api';
import { registrarPagina, getPaginas } from '../registry/tabRegistry';
import { useToast } from '../hooks/useToast';
import Toast from '../components/Toast';
import styles from './ConfigOperaciones.module.css';

registrarPagina({
  pagePath: '/config-operaciones',
  pageLabel: 'Configuración',
  tabs: [
    { tabKey: 'operadores', label: 'Operadores' },
    { tabKey: 'costos', label: 'Costos Envío' },
    { tabKey: 'logisticas', label: 'Logísticas' },
    { tabKey: 'transportes', label: 'Transportes' },
  ],
});


// ══════════════════════════════════════════════════════════════════════
// Tab: Operadores
// ══════════════════════════════════════════════════════════════════════

function TabOperadores() {
  const [operadores, setOperadores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [incluirInactivos, setIncluirInactivos] = useState(false);
  const [error, setError] = useState(null);

  // Crear form
  const [formPin, setFormPin] = useState('');
  const [formNombre, setFormNombre] = useState('');
  const [creating, setCreating] = useState(false);

  // Editar inline
  const [editId, setEditId] = useState(null);
  const [editNombre, setEditNombre] = useState('');
  const [editPin, setEditPin] = useState('');

  // Config tabs
  const [configTabs, setConfigTabs] = useState([]);
  const [selectedPagePath, setSelectedPagePath] = useState('');
  const [selectedTabKey, setSelectedTabKey] = useState('');
  const [tabFormTimeout, setTabFormTimeout] = useState(15);
  const [creatingTab, setCreatingTab] = useState(false);

  // Catálogo dinámico desde el registry
  const PAGINAS_TABS_MEMO = useMemo(() => getPaginas(), []);

  // Tabs disponibles filtradas (excluye las ya configuradas)
  const selectedPage = useMemo(
    () => PAGINAS_TABS_MEMO.find((p) => p.pagePath === selectedPagePath),
    [PAGINAS_TABS_MEMO, selectedPagePath]
  );

  const tabsDisponibles = useMemo(() => {
    if (!selectedPage) return [];
    const yaConfiguradas = new Set(
      configTabs
        .filter((ct) => ct.page_path === selectedPagePath)
        .map((ct) => ct.tab_key)
    );
    return selectedPage.tabs.filter((t) => !yaConfiguradas.has(t.tabKey));
  }, [selectedPage, selectedPagePath, configTabs]);

  const cargarOperadores = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = incluirInactivos ? '?incluir_inactivos=true' : '';
      const { data } = await api.get(`/config-operaciones/operadores${params}`);
      setOperadores(data);
    } catch {
      setError('Error al cargar operadores');
    } finally {
      setLoading(false);
    }
  }, [incluirInactivos]);

  const cargarConfigTabs = useCallback(async () => {
    try {
      const { data } = await api.get('/config-operaciones/tabs');
      setConfigTabs(data);
    } catch {
      // silencioso, no es crítico
    }
  }, []);

  useEffect(() => {
    cargarOperadores();
    cargarConfigTabs();
  }, [cargarOperadores, cargarConfigTabs]);

  const crearOperador = async (e) => {
    e.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await api.post('/config-operaciones/operadores', {
        pin: formPin,
        nombre: formNombre,
      });
      setFormPin('');
      setFormNombre('');
      await cargarOperadores();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear operador');
    } finally {
      setCreating(false);
    }
  };

  const toggleActivo = async (op) => {
    try {
      await api.put(`/config-operaciones/operadores/${op.id}`, {
        activo: !op.activo,
      });
      await cargarOperadores();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al actualizar operador');
    }
  };

  const iniciarEdicion = (op) => {
    setEditId(op.id);
    setEditNombre(op.nombre);
    setEditPin(op.pin);
  };

  const guardarEdicion = async () => {
    if (!editId) return;
    try {
      await api.put(`/config-operaciones/operadores/${editId}`, {
        nombre: editNombre,
        pin: editPin,
      });
      setEditId(null);
      await cargarOperadores();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar cambios');
    }
  };

  const cancelarEdicion = () => {
    setEditId(null);
  };

  const crearConfigTab = async (e) => {
    e.preventDefault();
    if (!selectedPagePath || !selectedTabKey) return;

    const pagina = PAGINAS_TABS_MEMO.find((p) => p.pagePath === selectedPagePath);
    const tab = pagina?.tabs.find((t) => t.tabKey === selectedTabKey);
    if (!pagina || !tab) return;

    setCreatingTab(true);
    setError(null);
    try {
      await api.post('/config-operaciones/tabs', {
        tab_key: selectedTabKey,
        page_path: selectedPagePath,
        label: tab.label,
        timeout_minutos: parseInt(tabFormTimeout, 10),
      });
      setSelectedPagePath('');
      setSelectedTabKey('');
      setTabFormTimeout(15);
      await cargarConfigTabs();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear config de tab');
    } finally {
      setCreatingTab(false);
    }
  };

  const eliminarConfigTab = async (tabId) => {
    try {
      await api.delete(`/config-operaciones/tabs/${tabId}`);
      await cargarConfigTabs();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al eliminar config');
    }
  };

  const toggleConfigTabActivo = async (tab) => {
    try {
      await api.put(`/config-operaciones/tabs/${tab.id}`, {
        activo: !tab.activo,
      });
      await cargarConfigTabs();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al actualizar config');
    }
  };

  return (
    <div className={styles.tabContent}>
      {error && <div className={styles.errorMsg}>{error}</div>}

      {/* ── Operadores Section ────────────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <Users size={20} /> Operadores
          </h2>
          <div className={styles.sectionActions}>
            <label className={styles.checkboxLabel}>
              <input
                type="checkbox"
                checked={incluirInactivos}
                onChange={(e) => setIncluirInactivos(e.target.checked)}
              />
              Mostrar inactivos
            </label>
            <button
              onClick={cargarOperadores}
              className={styles.btnRefresh}
              disabled={loading}
              aria-label="Actualizar lista"
            >
              <RefreshCw size={16} className={loading ? styles.spinning : ''} />
            </button>
          </div>
        </div>

        {/* Create form */}
        <form onSubmit={crearOperador} className={styles.createForm}>
          <div className={styles.formField}>
            <label htmlFor="op-pin">PIN (4 dígitos)</label>
            <input
              id="op-pin"
              type="text"
              inputMode="numeric"
              pattern="\d{4}"
              maxLength={4}
              value={formPin}
              onChange={(e) => setFormPin(e.target.value.replace(/\D/g, ''))}
              placeholder="0000"
              required
              className={styles.inputPin}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="op-nombre">Nombre</label>
            <input
              id="op-nombre"
              type="text"
              value={formNombre}
              onChange={(e) => setFormNombre(e.target.value)}
              placeholder="Nombre del operador"
              required
              maxLength={100}
            />
          </div>
          <button
            type="submit"
            className="btn-tesla outline-subtle-primary"
            disabled={creating || formPin.length !== 4}
          >
            <Plus size={16} />
            {creating ? 'Creando...' : 'Crear'}
          </button>
        </form>

        {/* Table */}
        {loading ? (
          <div className={styles.loading}>Cargando operadores...</div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th><Hash size={14} /> PIN</th>
                  <th>Nombre</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {operadores.length === 0 ? (
                  <tr>
                    <td colSpan={4} className={styles.empty}>
                      No hay operadores {incluirInactivos ? '' : 'activos'}
                    </td>
                  </tr>
                ) : (
                  operadores.map((op) => (
                    <tr key={op.id} className={!op.activo ? styles.rowInactiva : ''}>
                      <td className={styles.pinCell}>
                        {editId === op.id ? (
                          <input
                            type="text"
                            inputMode="numeric"
                            pattern="\d{4}"
                            maxLength={4}
                            value={editPin}
                            onChange={(e) => setEditPin(e.target.value.replace(/\D/g, ''))}
                            className={styles.inputPinEdit}
                          />
                        ) : (
                          <code className={styles.pinCode}>{op.pin}</code>
                        )}
                      </td>
                      <td>
                        {editId === op.id ? (
                          <input
                            type="text"
                            value={editNombre}
                            onChange={(e) => setEditNombre(e.target.value)}
                            className={styles.inputNombreEdit}
                            maxLength={100}
                          />
                        ) : (
                          op.nombre
                        )}
                      </td>
                      <td>
                        <span
                          className={`${styles.badge} ${op.activo ? styles.badgeActivo : styles.badgeInactivo}`}
                        >
                          {op.activo ? 'Activo' : 'Inactivo'}
                        </span>
                      </td>
                      <td className={styles.actions}>
                        {editId === op.id ? (
                          <>
                            <button
                              onClick={guardarEdicion}
                              className={styles.btnAction}
                              title="Guardar"
                              aria-label="Guardar cambios"
                            >
                              <Save size={16} />
                            </button>
                            <button
                              onClick={cancelarEdicion}
                              className={styles.btnAction}
                              title="Cancelar"
                              aria-label="Cancelar edición"
                            >
                              ×
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => iniciarEdicion(op)}
                              className={styles.btnAction}
                              title="Editar"
                              aria-label="Editar operador"
                            >
                              <Save size={16} />
                            </button>
                            <button
                              onClick={() => toggleActivo(op)}
                              className={styles.btnAction}
                              title={op.activo ? 'Desactivar' : 'Activar'}
                              aria-label={op.activo ? 'Desactivar operador' : 'Activar operador'}
                            >
                              {op.activo ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Config Tabs PIN Section ───────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <Clock size={20} /> Tabs con PIN
          </h2>
        </div>
        <p className={styles.sectionDesc}>
          Configurá qué tabs de la app requieren que el operador se identifique con PIN.
          El timeout define cuántos minutos de inactividad antes de pedir el PIN de nuevo.
        </p>

        {/* Create form — dropdowns en cascada */}
        <form onSubmit={crearConfigTab} className={styles.createForm}>
          <div className={styles.formField}>
            <label htmlFor="tab-page">Página</label>
            <div className={styles.selectWrapper}>
              <select
                id="tab-page"
                value={selectedPagePath}
                onChange={(e) => {
                  setSelectedPagePath(e.target.value);
                  setSelectedTabKey('');
                }}
                className={styles.select}
                required
              >
                <option value="">Seleccionar página...</option>
                {PAGINAS_TABS_MEMO.map((p) => (
                  <option key={p.pagePath} value={p.pagePath}>
                    {p.pageLabel}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} className={styles.selectIcon} />
            </div>
          </div>
          <div className={styles.formField}>
            <label htmlFor="tab-key">Tab</label>
            <div className={styles.selectWrapper}>
              <select
                id="tab-key"
                value={selectedTabKey}
                onChange={(e) => setSelectedTabKey(e.target.value)}
                className={styles.select}
                required
                disabled={!selectedPagePath || tabsDisponibles.length === 0}
              >
                <option value="">
                  {!selectedPagePath
                    ? 'Elegí una página primero...'
                    : tabsDisponibles.length === 0
                      ? 'Todas las tabs ya están configuradas'
                      : 'Seleccionar tab...'}
                </option>
                {tabsDisponibles.map((t) => (
                  <option key={t.tabKey} value={t.tabKey}>
                    {t.label}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} className={styles.selectIcon} />
            </div>
          </div>
          <div className={styles.formField}>
            <label htmlFor="tab-timeout">Timeout (min)</label>
            <input
              id="tab-timeout"
              type="number"
              min={1}
              max={480}
              value={tabFormTimeout}
              onChange={(e) => setTabFormTimeout(e.target.value)}
              className={styles.inputSmall}
            />
          </div>
          <button
            type="submit"
            className="btn-tesla outline-subtle-primary"
            disabled={creatingTab || !selectedPagePath || !selectedTabKey}
          >
            <Plus size={16} />
            {creatingTab ? 'Creando...' : 'Agregar'}
          </button>
        </form>

        {/* Table */}
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Página</th>
                <th>Tab</th>
                <th>Timeout</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {configTabs.length === 0 ? (
                <tr>
                  <td colSpan={5} className={styles.empty}>
                    No hay tabs configurados
                  </td>
                </tr>
              ) : (
                configTabs.map((tab) => {
                  const pagina = PAGINAS_TABS_MEMO.find((p) => p.pagePath === tab.page_path);
                  return (
                  <tr key={tab.id} className={!tab.activo ? styles.rowInactiva : ''}>
                    <td>{pagina?.pageLabel || tab.page_path}</td>
                    <td>{tab.label}</td>
                    <td>{tab.timeout_minutos} min</td>
                    <td>
                      <span
                        className={`${styles.badge} ${tab.activo ? styles.badgeActivo : styles.badgeInactivo}`}
                      >
                        {tab.activo ? 'Activo' : 'Inactivo'}
                      </span>
                    </td>
                    <td className={styles.actions}>
                      <button
                        onClick={() => toggleConfigTabActivo(tab)}
                        className={styles.btnAction}
                        title={tab.activo ? 'Desactivar' : 'Activar'}
                        aria-label={tab.activo ? 'Desactivar tab' : 'Activar tab'}
                      >
                        {tab.activo ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                      </button>
                      <button
                        onClick={() => eliminarConfigTab(tab.id)}
                        className={styles.btnAction}
                        title="Eliminar"
                        aria-label="Eliminar config de tab"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════════
// Tab: Costos Envío
// ══════════════════════════════════════════════════════════════════════

const CORDONES = ['CABA', 'Cordon 1', 'Cordon 2', 'Cordon 3'];

function TabCostosEnvio() {
  const [costos, setCostos] = useState([]);
  const [logisticas, setLogisticas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  // Editable matrices: { `${logistica_id}-${cordon}`: valor }
  const [matrix, setMatrix] = useState({});
  const [turboMatrix, setTurboMatrix] = useState({});
  // Original values from backend (for change detection via string comparison)
  const [origMatrix, setOrigMatrix] = useState({});
  const [origTurboMatrix, setOrigTurboMatrix] = useState({});
  // Per-logística vigente dates: { logistica_id: 'YYYY-MM-DD' }
  const [vigenteMap, setVigenteMap] = useState({});
  const [origVigenteMap, setOrigVigenteMap] = useState({});
  const defaultDate = () => new Date().toISOString().split('T')[0];

  const { toast, showToast, hideToast } = useToast();

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [costosRes, logisticasRes] = await Promise.all([
        api.get('/config-operaciones/costos'),
        api.get('/logisticas?incluir_inactivas=false'),
      ]);
      setCostos(costosRes.data);
      setLogisticas(logisticasRes.data);

      // Construir matrices desde datos existentes
      const m = {};
      const mt = {};
      for (const c of costosRes.data) {
        const key = `${c.logistica_id}-${c.cordon}`;
        m[key] = c.costo.toString();
        mt[key] = c.costo_turbo != null ? c.costo_turbo.toString() : '';
      }
      // Construir fechas vigentes por logística: tomar la del registro con mayor id
      // (el último guardado por el usuario, consistente con max(id) del backend)
      const v = {};
      const vMaxId = {};
      for (const c of costosRes.data) {
        if (!vMaxId[c.logistica_id] || c.id > vMaxId[c.logistica_id]) {
          vMaxId[c.logistica_id] = c.id;
          v[c.logistica_id] = c.vigente_desde;
        }
      }

      setMatrix(m);
      setTurboMatrix(mt);
      setVigenteMap(v);
      // Snapshot originals for string-based change detection
      setOrigMatrix({ ...m });
      setOrigTurboMatrix({ ...mt });
      setOrigVigenteMap({ ...v });
    } catch {
      setError('Error al cargar costos');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const handleCostChange = (logisticaId, cordon, valor) => {
    setMatrix((prev) => ({
      ...prev,
      [`${logisticaId}-${cordon}`]: valor,
    }));
  };

  const handleTurboCostChange = (logisticaId, cordon, valor) => {
    setTurboMatrix((prev) => ({
      ...prev,
      [`${logisticaId}-${cordon}`]: valor,
    }));
  };

  const getCostoActual = (logisticaId, cordon) => {
    return costos.find(
      (c) => c.logistica_id === logisticaId && c.cordon === cordon
    );
  };

  // Check if a specific cell has changes (value or date)
  const hasChanges = (logisticaId, cordon) => {
    const key = `${logisticaId}-${cordon}`;
    const valorMatrix = matrix[key] ?? '';
    const turboValMatrix = turboMatrix[key] ?? '';
    const origVal = origMatrix[key] ?? '';
    const origTurbo = origTurboMatrix[key] ?? '';
    const fechaActual = vigenteMap[logisticaId] || '';
    const fechaOrig = origVigenteMap[logisticaId] || '';
    return valorMatrix !== origVal || turboValMatrix !== origTurbo || fechaActual !== fechaOrig;
  };

  // Check if any cell in a row has changes
  const rowHasChanges = (logisticaId) =>
    CORDONES.some((cordon) => hasChanges(logisticaId, cordon));

  // Save all changed cells for a logística row
  const guardarFila = async (logisticaId) => {
    const fecha = vigenteMap[logisticaId] || defaultDate();
    const cordonesConCambios = CORDONES.filter((c) => hasChanges(logisticaId, c));

    if (cordonesConCambios.length === 0) return;

    // Validate all before saving
    for (const cordon of cordonesConCambios) {
      const key = `${logisticaId}-${cordon}`;
      const valor = parseFloat(matrix[key]);
      if (isNaN(valor) || valor < 0) {
        setError(`Costo inválido en ${cordon}`);
        return;
      }
      const turboRaw = turboMatrix[key];
      if (turboRaw !== '') {
        const tv = parseFloat(turboRaw);
        if (isNaN(tv) || tv < 0) {
          setError(`Costo turbo inválido en ${cordon}`);
          return;
        }
      }
    }

    setSaving(true);
    setError(null);
    try {
      const promises = cordonesConCambios.map((cordon) => {
        const key = `${logisticaId}-${cordon}`;
        const valor = parseFloat(matrix[key]);
        const turboRaw = turboMatrix[key];
        const actual = getCostoActual(logisticaId, cordon);
        const turboVal = turboRaw !== '' ? parseFloat(turboRaw) : actual?.costo_turbo ?? null;

        return api.post('/config-operaciones/costos', {
          logistica_id: logisticaId,
          cordon,
          costo: valor,
          costo_turbo: turboVal,
          vigente_desde: fecha,
        });
      });

      await Promise.all(promises);
      await cargarDatos();
      showToast(`${cordonesConCambios.length} cordón(es) guardado(s)`);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar costos');
    } finally {
      setSaving(false);
    }
  };

  // Check if ANY logística has changes (for "Guardar todo" visibility)
  const anyChanges = logisticas.some((log) => rowHasChanges(log.id));

  // Save ALL logísticas that have changes
  const guardarTodo = async () => {
    const logisticasConCambios = logisticas.filter((log) => rowHasChanges(log.id));
    if (logisticasConCambios.length === 0) return;

    setSaving(true);
    setError(null);
    try {
      const allPromises = logisticasConCambios.flatMap((log) => {
        const fecha = vigenteMap[log.id] || defaultDate();
        return CORDONES.filter((c) => hasChanges(log.id, c)).map((cordon) => {
          const key = `${log.id}-${cordon}`;
          const valor = parseFloat(matrix[key]);
          if (isNaN(valor) || valor < 0) {
            throw new Error(`Costo inválido en ${log.nombre} — ${cordon}`);
          }
          const turboRaw = turboMatrix[key];
          if (turboRaw !== '') {
            const tv = parseFloat(turboRaw);
            if (isNaN(tv) || tv < 0) {
              throw new Error(`Costo turbo inválido en ${log.nombre} — ${cordon}`);
            }
          }
          const actual = getCostoActual(log.id, cordon);
          const turboVal = turboRaw !== '' ? parseFloat(turboRaw) : actual?.costo_turbo ?? null;

          return api.post('/config-operaciones/costos', {
            logistica_id: log.id,
            cordon,
            costo: valor,
            costo_turbo: turboVal,
            vigente_desde: fecha,
          });
        });
      });

      await Promise.all(allPromises);
      await cargarDatos();
      showToast(`${logisticasConCambios.length} logística(s) guardada(s)`);
    } catch (err) {
      setError(err.message || err.response?.data?.detail || 'Error al guardar costos');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className={styles.loading}>Cargando costos de envío...</div>;
  }

  return (
    <div className={styles.tabContent}>
      {error && <div className={styles.errorMsg}>{error}</div>}

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <DollarSign size={20} /> Costos por Logística y Cordón
          </h2>
          <div className={styles.sectionActions}>
            {anyChanges && (
              <button
                onClick={guardarTodo}
                className="btn-tesla outline-subtle-primary"
                disabled={saving}
                aria-label="Guardar todos los cambios"
              >
                <Save size={16} />
                {saving ? 'Guardando...' : 'Guardar todo'}
              </button>
            )}
            <button
              onClick={cargarDatos}
              className={styles.btnRefresh}
              aria-label="Actualizar costos"
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        <p className={styles.sectionDesc}>
          Editá los costos para cada logística y cordón. Cada logística tiene su propia
          fecha de vigencia. Al guardar se crea un nuevo registro histórico.
        </p>

        {logisticas.length === 0 ? (
          <div className={styles.empty}>
            No hay logísticas activas. Crealas primero en la pestaña Logísticas.
          </div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Logística</th>
                  {CORDONES.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logisticas.map((log) => (
                  <tr key={log.id}>
                    <td className={styles.logisticaCell}>
                      <div className={styles.logisticaName}>
                        {log.color && (
                          <span
                            className={styles.colorDot}
                            style={{ background: log.color }}
                          />
                        )}
                        {log.nombre}
                      </div>
                      <input
                        type="date"
                        value={vigenteMap[log.id] || defaultDate()}
                        onChange={(e) =>
                          setVigenteMap((prev) => ({
                            ...prev,
                            [log.id]: e.target.value,
                          }))
                        }
                        className={styles.logisticaDate}
                        title="Fecha de vigencia para esta logística"
                      />
                      {rowHasChanges(log.id) && (
                        <button
                          onClick={() => guardarFila(log.id)}
                          className={styles.btnGuardarFila}
                          disabled={saving}
                          title="Guardar esta logística (o Enter)"
                          aria-label={`Guardar cambios de ${log.nombre}`}
                        >
                          <Save size={14} />
                          Guardar
                        </button>
                      )}
                    </td>
                    {CORDONES.map((cordon) => {
                      const key = `${log.id}-${cordon}`;
                      const actual = getCostoActual(log.id, cordon);
                      const valorMatrix = matrix[key] ?? '';
                      const turboValMatrix = turboMatrix[key] ?? '';
                      const cellChanged = hasChanges(log.id, cordon);

                      return (
                        <td key={cordon} className={`${styles.costoCell} ${cellChanged ? styles.costoCellChanged : ''}`}>
                          <div className={styles.costoRows}>
                            <div className={styles.costoInputGroup}>
                              <span className={styles.costoPrefix}>$</span>
                              <input
                                type="number"
                                min={0}
                                step="0.01"
                                value={valorMatrix}
                                onChange={(e) =>
                                  handleCostChange(log.id, cordon, e.target.value)
                                }
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' && rowHasChanges(log.id)) {
                                    e.preventDefault();
                                    guardarFila(log.id);
                                  }
                                }}
                                className={styles.costoInput}
                                placeholder="—"
                              />
                            </div>
                            <div className={styles.costoInputGroup}>
                              <span className={styles.costoPrefixTurbo}>T$</span>
                              <input
                                type="number"
                                min={0}
                                step="0.01"
                                value={turboValMatrix}
                                onChange={(e) =>
                                  handleTurboCostChange(log.id, cordon, e.target.value)
                                }
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' && rowHasChanges(log.id)) {
                                    e.preventDefault();
                                    guardarFila(log.id);
                                  }
                                }}
                                className={styles.costoInput}
                                placeholder="—"
                              />
                            </div>
                          </div>
                          {actual && (
                            <span className={styles.costoVigente}>
                              desde {actual.vigente_desde}
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════════
// Tab: Logísticas
// ══════════════════════════════════════════════════════════════════════

function TabLogisticas() {
  const [logisticas, setLogisticas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Create form
  const [newNombre, setNewNombre] = useState('');
  const [newColor, setNewColor] = useState('#3b82f6');
  const [creating, setCreating] = useState(false);

  const cargarLogisticas = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/logisticas?incluir_inactivas=true');
      setLogisticas(data);
    } catch {
      setError('Error al cargar logísticas');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargarLogisticas();
  }, [cargarLogisticas]);

  const crearLogistica = async (e) => {
    e.preventDefault();
    if (!newNombre.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await api.post('/logisticas', {
        nombre: newNombre.trim(),
        color: newColor,
      });
      setNewNombre('');
      setNewColor('#3b82f6');
      await cargarLogisticas();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear logística');
    } finally {
      setCreating(false);
    }
  };

  const toggleActiva = async (log) => {
    try {
      await api.put(`/logisticas/${log.id}`, {
        activa: !log.activa,
      });
      await cargarLogisticas();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al actualizar logística');
    }
  };

  const desactivar = async (log) => {
    try {
      await api.delete(`/logisticas/${log.id}`);
      await cargarLogisticas();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al desactivar logística');
    }
  };

  return (
    <div className={styles.tabContent}>
      {error && <div className={styles.errorMsg}>{error}</div>}

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <Truck size={20} /> Logísticas de Envío
          </h2>
          <button
            onClick={cargarLogisticas}
            className={styles.btnRefresh}
            disabled={loading}
            aria-label="Actualizar logísticas"
          >
            <RefreshCw size={16} className={loading ? styles.spinning : ''} />
          </button>
        </div>
        <p className={styles.sectionDesc}>
          Gestioná las logísticas disponibles para asignar a envíos flex.
          Cada logística tiene un color que se muestra en las etiquetas.
        </p>

        {/* Create form */}
        <form onSubmit={crearLogistica} className={styles.createForm}>
          <div className={styles.formField}>
            <label htmlFor="log-nombre">Nombre</label>
            <input
              id="log-nombre"
              type="text"
              value={newNombre}
              onChange={(e) => setNewNombre(e.target.value)}
              placeholder="Ej: Andreani"
              required
              maxLength={100}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="log-color">Color</label>
            <input
              id="log-color"
              type="color"
              value={newColor}
              onChange={(e) => setNewColor(e.target.value)}
              className={styles.colorInput}
            />
          </div>
          <button
            type="submit"
            className="btn-tesla outline-subtle-primary"
            disabled={creating || !newNombre.trim()}
          >
            <Plus size={16} />
            {creating ? 'Creando...' : 'Crear'}
          </button>
        </form>

        {/* List */}
        {loading ? (
          <div className={styles.loading}>Cargando logísticas...</div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Color</th>
                  <th>Nombre</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {logisticas.length === 0 ? (
                  <tr>
                    <td colSpan={4} className={styles.empty}>
                      No hay logísticas creadas
                    </td>
                  </tr>
                ) : (
                  logisticas.map((log) => (
                    <tr key={log.id} className={!log.activa ? styles.rowInactiva : ''}>
                      <td>
                        <span
                          className={styles.colorDot}
                          style={{ background: log.color || '#94a3b8' }}
                        />
                      </td>
                      <td>{log.nombre}</td>
                      <td>
                        <span
                          className={`${styles.badge} ${log.activa ? styles.badgeActivo : styles.badgeInactivo}`}
                        >
                          {log.activa ? 'Activa' : 'Inactiva'}
                        </span>
                      </td>
                      <td className={styles.actions}>
                        <button
                          onClick={() => toggleActiva(log)}
                          className={styles.btnAction}
                          title={log.activa ? 'Desactivar' : 'Activar'}
                          aria-label={log.activa ? 'Desactivar logística' : 'Activar logística'}
                        >
                          {log.activa ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                        </button>
                        {log.activa && (
                          <button
                            onClick={() => desactivar(log)}
                            className={styles.btnAction}
                            title="Desactivar"
                            aria-label="Desactivar logística"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════════
// Tab: Transportes
// ══════════════════════════════════════════════════════════════════════

function TabTransportes() {
  const [transportes, setTransportes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Create form
  const [newNombre, setNewNombre] = useState('');
  const [newCuit, setNewCuit] = useState('');
  const [newDireccion, setNewDireccion] = useState('');
  const [newTelefono, setNewTelefono] = useState('');
  const [newHorario, setNewHorario] = useState('');
  const [newColor, setNewColor] = useState('#8b5cf6');
  const [creating, setCreating] = useState(false);

  const cargarTransportes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get('/transportes?incluir_inactivas=true');
      setTransportes(data);
    } catch {
      setError('Error al cargar transportes');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargarTransportes();
  }, [cargarTransportes]);

  const crearTransporte = async (e) => {
    e.preventDefault();
    if (!newNombre.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await api.post('/transportes', {
        nombre: newNombre.trim(),
        cuit: newCuit.trim() || null,
        direccion: newDireccion.trim() || null,
        telefono: newTelefono.trim() || null,
        horario: newHorario.trim() || null,
        color: newColor,
      });
      setNewNombre('');
      setNewCuit('');
      setNewDireccion('');
      setNewTelefono('');
      setNewHorario('');
      setNewColor('#8b5cf6');
      await cargarTransportes();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear transporte');
    } finally {
      setCreating(false);
    }
  };

  const toggleActiva = async (t) => {
    try {
      await api.put(`/transportes/${t.id}`, {
        activa: !t.activa,
      });
      await cargarTransportes();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al actualizar transporte');
    }
  };

  const desactivar = async (t) => {
    try {
      await api.delete(`/transportes/${t.id}`);
      await cargarTransportes();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al desactivar transporte');
    }
  };

  return (
    <div className={styles.tabContent}>
      {error && <div className={styles.errorMsg}>{error}</div>}

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            <Building size={20} /> Transportes Interprovinciales
          </h2>
          <button
            onClick={cargarTransportes}
            className={styles.btnRefresh}
            disabled={loading}
            aria-label="Actualizar transportes"
          >
            <RefreshCw size={16} className={loading ? styles.spinning : ''} />
          </button>
        </div>
        <p className={styles.sectionDesc}>
          Gestioná los transportes interprovinciales disponibles para asignar a envíos flex.
          Incluyen dirección de terminal, teléfono y horario de recepción.
        </p>

        {/* Create form */}
        <form onSubmit={crearTransporte} className={styles.createForm}>
          <div className={styles.formField}>
            <label htmlFor="transp-nombre">Nombre</label>
            <input
              id="transp-nombre"
              type="text"
              value={newNombre}
              onChange={(e) => setNewNombre(e.target.value)}
              placeholder="Ej: Cruz del Sur"
              required
              maxLength={150}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="transp-cuit">CUIT</label>
            <input
              id="transp-cuit"
              type="text"
              value={newCuit}
              onChange={(e) => setNewCuit(e.target.value)}
              placeholder="30-12345678-9"
              maxLength={13}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="transp-direccion">Dirección</label>
            <input
              id="transp-direccion"
              type="text"
              value={newDireccion}
              onChange={(e) => setNewDireccion(e.target.value)}
              placeholder="Terminal/depósito"
              maxLength={500}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="transp-telefono">Teléfono</label>
            <input
              id="transp-telefono"
              type="text"
              value={newTelefono}
              onChange={(e) => setNewTelefono(e.target.value)}
              placeholder="011-4444-5555"
              maxLength={50}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="transp-horario">Horario</label>
            <input
              id="transp-horario"
              type="text"
              value={newHorario}
              onChange={(e) => setNewHorario(e.target.value)}
              placeholder="Lun-Vie 8-17"
              maxLength={200}
            />
          </div>
          <div className={styles.formField}>
            <label htmlFor="transp-color">Color</label>
            <input
              id="transp-color"
              type="color"
              value={newColor}
              onChange={(e) => setNewColor(e.target.value)}
              className={styles.colorInput}
            />
          </div>
          <button
            type="submit"
            className="btn-tesla outline-subtle-primary"
            disabled={creating || !newNombre.trim()}
          >
            <Plus size={16} />
            {creating ? 'Creando...' : 'Crear'}
          </button>
        </form>

        {/* List */}
        {loading ? (
          <div className={styles.loading}>Cargando transportes...</div>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Color</th>
                  <th>Nombre</th>
                  <th>CUIT</th>
                  <th>Dirección</th>
                  <th>Teléfono</th>
                  <th>Horario</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {transportes.length === 0 ? (
                  <tr>
                    <td colSpan={8} className={styles.empty}>
                      No hay transportes creados
                    </td>
                  </tr>
                ) : (
                  transportes.map((t) => (
                    <tr key={t.id} className={!t.activa ? styles.rowInactiva : ''}>
                      <td>
                        <span
                          className={styles.colorDot}
                          style={{ background: t.color || '#94a3b8' }}
                        />
                      </td>
                      <td>{t.nombre}</td>
                      <td>{t.cuit || '—'}</td>
                      <td>{t.direccion || '—'}</td>
                      <td>{t.telefono || '—'}</td>
                      <td>{t.horario || '—'}</td>
                      <td>
                        <span
                          className={`${styles.badge} ${t.activa ? styles.badgeActivo : styles.badgeInactivo}`}
                        >
                          {t.activa ? 'Activo' : 'Inactivo'}
                        </span>
                      </td>
                      <td className={styles.actions}>
                        <button
                          onClick={() => toggleActiva(t)}
                          className={styles.btnAction}
                          title={t.activa ? 'Desactivar' : 'Activar'}
                          aria-label={t.activa ? 'Desactivar transporte' : 'Activar transporte'}
                        >
                          {t.activa ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                        </button>
                        {t.activa && (
                          <button
                            onClick={() => desactivar(t)}
                            className={styles.btnAction}
                            title="Desactivar"
                            aria-label="Desactivar transporte"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}


// ══════════════════════════════════════════════════════════════════════
// Main Page Component
// ══════════════════════════════════════════════════════════════════════

export default function ConfigOperaciones() {
  const [tabActiva, setTabActiva] = useState('operadores');

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>Config Operaciones</h1>
      </div>

      {/* Tab navigation */}
      <div className={styles.tabsContainer}>
        <button
          className={`${styles.tabBtn} ${tabActiva === 'operadores' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('operadores')}
        >
          <Users size={16} /> Operadores
        </button>
        <button
          className={`${styles.tabBtn} ${tabActiva === 'costos' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('costos')}
        >
          <DollarSign size={16} /> Costos Envío
        </button>
        <button
          className={`${styles.tabBtn} ${tabActiva === 'logisticas' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('logisticas')}
        >
          <Truck size={16} /> Logísticas
        </button>
        <button
          className={`${styles.tabBtn} ${tabActiva === 'transportes' ? styles.tabActiva : ''}`}
          onClick={() => setTabActiva('transportes')}
        >
          <Building size={16} /> Transportes
        </button>
      </div>

      {/* Tab content */}
      {tabActiva === 'operadores' && <TabOperadores />}
      {tabActiva === 'costos' && <TabCostosEnvio />}
      {tabActiva === 'logisticas' && <TabLogisticas />}
      {tabActiva === 'transportes' && <TabTransportes />}
    </div>
  );
}
