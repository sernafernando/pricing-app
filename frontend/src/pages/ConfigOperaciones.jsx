import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Users, DollarSign, Truck, Plus, ToggleLeft, ToggleRight,
  Trash2, Save, RefreshCw, Clock, Hash, ChevronDown,
} from 'lucide-react';
import api from '../services/api';
import { usePermisos } from '../contexts/PermisosContext';
import { registrarPagina, getPaginas } from '../registry/tabRegistry';
import styles from './ConfigOperaciones.module.css';

registrarPagina({
  pagePath: '/config-operaciones',
  pageLabel: 'Configuración',
  tabs: [
    { tabKey: 'operadores', label: 'Operadores' },
    { tabKey: 'costos', label: 'Costos Envío' },
    { tabKey: 'logisticas', label: 'Logísticas' },
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
    } catch (err) {
      setError('Error al cargar operadores');
    } finally {
      setLoading(false);
    }
  }, [incluirInactivos]);

  const cargarConfigTabs = useCallback(async () => {
    try {
      const { data } = await api.get('/config-operaciones/tabs');
      setConfigTabs(data);
    } catch (err) {
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
            className={styles.btnCrear}
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
            className={styles.btnCrear}
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

  // Editable matrix: { `${logistica_id}-${cordon}`: valor }
  const [matrix, setMatrix] = useState({});
  const [vigente, setVigente] = useState(() => {
    const hoy = new Date();
    return hoy.toISOString().split('T')[0];
  });

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

      // Construir matrix desde datos existentes
      const m = {};
      for (const c of costosRes.data) {
        m[`${c.logistica_id}-${c.cordon}`] = c.costo.toString();
      }
      setMatrix(m);
    } catch (err) {
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

  const guardarCosto = async (logisticaId, cordon) => {
    const key = `${logisticaId}-${cordon}`;
    const valor = parseFloat(matrix[key]);
    if (isNaN(valor) || valor < 0) {
      setError('Ingresá un costo válido (mayor o igual a 0)');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await api.post('/config-operaciones/costos', {
        logistica_id: logisticaId,
        cordon: cordon,
        costo: valor,
        vigente_desde: vigente,
      });
      await cargarDatos();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar costo');
    } finally {
      setSaving(false);
    }
  };

  const getCostoActual = (logisticaId, cordon) => {
    return costos.find(
      (c) => c.logistica_id === logisticaId && c.cordon === cordon
    );
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
            <div className={styles.formField}>
              <label htmlFor="vigente-desde">Vigente desde</label>
              <input
                id="vigente-desde"
                type="date"
                value={vigente}
                onChange={(e) => setVigente(e.target.value)}
                className={styles.inputDate}
              />
            </div>
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
          Editá los costos para cada logística y cordón. Al guardar, se crea un nuevo
          registro con la fecha de vigencia seleccionada. Los precios anteriores quedan
          como historial.
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
                      {log.color && (
                        <span
                          className={styles.colorDot}
                          style={{ background: log.color }}
                        />
                      )}
                      {log.nombre}
                    </td>
                    {CORDONES.map((cordon) => {
                      const key = `${log.id}-${cordon}`;
                      const actual = getCostoActual(log.id, cordon);
                      const valorMatrix = matrix[key] ?? '';
                      const changed = actual
                        ? parseFloat(valorMatrix) !== actual.costo
                        : valorMatrix !== '';

                      return (
                        <td key={cordon} className={styles.costoCell}>
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
                              className={styles.costoInput}
                              placeholder="—"
                            />
                            {changed && (
                              <button
                                onClick={() => guardarCosto(log.id, cordon)}
                                className={styles.btnSaveCosto}
                                disabled={saving}
                                title="Guardar nuevo costo"
                                aria-label={`Guardar costo de ${log.nombre} para ${cordon}`}
                              >
                                <Save size={14} />
                              </button>
                            )}
                          </div>
                          {actual && (
                            <div className={styles.costoVigente}>
                              desde {actual.vigente_desde}
                            </div>
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
    } catch (err) {
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
            className={styles.btnCrear}
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
      </div>

      {/* Tab content */}
      {tabActiva === 'operadores' && <TabOperadores />}
      {tabActiva === 'costos' && <TabCostosEnvio />}
      {tabActiva === 'logisticas' && <TabLogisticas />}
    </div>
  );
}
