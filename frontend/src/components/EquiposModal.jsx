import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, Users, Pencil, Check, X } from 'lucide-react';
import api, { equiposAPI } from '../services/api';
import ModalTesla, { ModalFooterButtons, ModalAlert, ModalLoading } from './ModalTesla';
import styles from './EquiposModal.module.css';

/**
 * EquiposModal — team management for the color-layer teams feature
 * (productos-color-teams).
 *
 * Lets any authenticated user create teams and manage the members of the teams
 * they administer: rename, delete, add/remove members and change their rol.
 *
 * Governance reflected here (enforced server-side, surfaced on error):
 * - The GLOBAL team (`es_global`) is never manageable — it is hidden from the
 *   manageable list, so no rename/delete/membership UI is ever offered for it.
 * - Membership mutations are admin-only; the backend rejects the removal or
 *   demotion of the sole admin (400 "último administrador") and the deletion of
 *   a team that still has colors (400 "tiene colores"). Both surface verbatim.
 */

const ROLES = [
  { value: 'miembro', label: 'Miembro' },
  { value: 'admin', label: 'Administrador' },
];

export default function EquiposModal({ isOpen, onClose }) {
  const [equipos, setEquipos] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [loadingEquipos, setLoadingEquipos] = useState(false);

  const [selectedId, setSelectedId] = useState(null);
  const [miembros, setMiembros] = useState([]);
  const [loadingMiembros, setLoadingMiembros] = useState(false);

  const [nuevoNombre, setNuevoNombre] = useState('');
  const [creando, setCreando] = useState(false);

  const [renombrando, setRenombrando] = useState(false);
  const [nombreEdit, setNombreEdit] = useState('');
  const [guardandoNombre, setGuardandoNombre] = useState(false);

  const [confirmarBorrado, setConfirmarBorrado] = useState(false);
  const [borrando, setBorrando] = useState(false);

  const [nuevoMiembroId, setNuevoMiembroId] = useState('');
  const [nuevoMiembroRol, setNuevoMiembroRol] = useState('miembro');
  const [agregando, setAgregando] = useState(false);

  // Per-member action in flight (usuario_id) so we can disable only its row.
  const [miembroBusy, setMiembroBusy] = useState(null);

  const [alerta, setAlerta] = useState(null); // { tipo: 'error' | 'success', texto }

  const showError = useCallback((err, fallback) => {
    setAlerta({ tipo: 'error', texto: err?.response?.data?.detail || fallback });
  }, []);
  const showSuccess = useCallback((texto) => {
    setAlerta({ tipo: 'success', texto });
  }, []);

  // Only non-global teams are manageable.
  const equiposManejables = equipos.filter((eq) => !eq.es_global);
  const selectedEquipo = equiposManejables.find((eq) => eq.id === selectedId) || null;

  const cargarEquipos = useCallback(async () => {
    setLoadingEquipos(true);
    try {
      const { data } = await equiposAPI.listar();
      setEquipos(Array.isArray(data) ? data : []);
      return Array.isArray(data) ? data : [];
    } catch (err) {
      showError(err, 'Error al cargar equipos');
      return [];
    } finally {
      setLoadingEquipos(false);
    }
  }, [showError]);

  const cargarMiembros = useCallback(async (equipoId) => {
    setLoadingMiembros(true);
    try {
      const { data } = await equiposAPI.listarMiembros(equipoId);
      setMiembros(Array.isArray(data) ? data : []);
    } catch (err) {
      setMiembros([]);
      showError(err, 'Error al cargar miembros');
    } finally {
      setLoadingMiembros(false);
    }
  }, [showError]);

  // Load teams + users each time the modal opens; reset transient state.
  useEffect(() => {
    if (!isOpen) return;
    setSelectedId(null);
    setMiembros([]);
    setNuevoNombre('');
    setRenombrando(false);
    setConfirmarBorrado(false);
    setNuevoMiembroId('');
    setNuevoMiembroRol('miembro');
    setAlerta(null);

    cargarEquipos();

    (async () => {
      try {
        const { data } = await api.get('/usuarios');
        setUsuarios(Array.isArray(data) ? data : []);
      } catch {
        setUsuarios([]);
      }
    })();
  }, [isOpen, cargarEquipos]);

  const seleccionar = (equipo) => {
    setSelectedId(equipo.id);
    setRenombrando(false);
    setConfirmarBorrado(false);
    setNuevoMiembroId('');
    setNuevoMiembroRol('miembro');
    setAlerta(null);
    cargarMiembros(equipo.id);
  };

  const crearEquipo = async () => {
    const nombre = nuevoNombre.trim();
    if (!nombre) return;
    setCreando(true);
    setAlerta(null);
    try {
      const { data } = await equiposAPI.crear({ nombre });
      setNuevoNombre('');
      showSuccess('Equipo creado');
      await cargarEquipos();
      if (data?.id) seleccionar(data);
    } catch (err) {
      showError(err, 'Error al crear el equipo');
    } finally {
      setCreando(false);
    }
  };

  const iniciarRenombrar = () => {
    if (!selectedEquipo) return;
    setNombreEdit(selectedEquipo.nombre);
    setRenombrando(true);
    setAlerta(null);
  };

  const guardarNombre = async () => {
    if (!selectedEquipo) return;
    const nombre = nombreEdit.trim();
    if (!nombre) return;
    setGuardandoNombre(true);
    setAlerta(null);
    try {
      await equiposAPI.actualizar(selectedEquipo.id, { nombre });
      showSuccess('Equipo renombrado');
      setRenombrando(false);
      await cargarEquipos();
    } catch (err) {
      showError(err, 'Error al renombrar el equipo');
    } finally {
      setGuardandoNombre(false);
    }
  };

  const eliminarEquipo = async () => {
    if (!selectedEquipo) return;
    setBorrando(true);
    setAlerta(null);
    try {
      await equiposAPI.eliminar(selectedEquipo.id);
      showSuccess('Equipo eliminado');
      setConfirmarBorrado(false);
      setSelectedId(null);
      setMiembros([]);
      await cargarEquipos();
    } catch (err) {
      // e.g. 400 "el equipo tiene colores marcados"
      showError(err, 'Error al eliminar el equipo');
    } finally {
      setBorrando(false);
    }
  };

  const agregarMiembro = async () => {
    if (!selectedEquipo || !nuevoMiembroId) return;
    setAgregando(true);
    setAlerta(null);
    try {
      await equiposAPI.agregarMiembro(selectedEquipo.id, {
        usuario_id: parseInt(nuevoMiembroId, 10),
        rol: nuevoMiembroRol,
      });
      setNuevoMiembroId('');
      setNuevoMiembroRol('miembro');
      showSuccess('Miembro agregado');
      await cargarMiembros(selectedEquipo.id);
    } catch (err) {
      showError(err, 'Error al agregar el miembro');
    } finally {
      setAgregando(false);
    }
  };

  const cambiarRol = async (miembro, rol) => {
    if (!selectedEquipo || rol === miembro.rol) return;
    setMiembroBusy(miembro.usuario_id);
    setAlerta(null);
    try {
      await equiposAPI.actualizarMiembro(selectedEquipo.id, miembro.usuario_id, { rol });
      await cargarMiembros(selectedEquipo.id);
    } catch (err) {
      // e.g. 400 "no se puede degradar al último administrador"
      showError(err, 'Error al cambiar el rol');
    } finally {
      setMiembroBusy(null);
    }
  };

  const quitarMiembro = async (miembro) => {
    if (!selectedEquipo) return;
    setMiembroBusy(miembro.usuario_id);
    setAlerta(null);
    try {
      await equiposAPI.eliminarMiembro(selectedEquipo.id, miembro.usuario_id);
      await cargarMiembros(selectedEquipo.id);
    } catch (err) {
      // e.g. 400 "no se puede quitar al último administrador"
      showError(err, 'Error al quitar el miembro');
    } finally {
      setMiembroBusy(null);
    }
  };

  const nombreUsuario = (uid) => {
    const u = usuarios.find((x) => x.id === uid);
    return u ? u.nombre || u.username || `Usuario #${uid}` : `Usuario #${uid}`;
  };

  const usuariosDisponibles = usuarios.filter(
    (u) => !miembros.some((m) => m.usuario_id === u.id),
  );

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Equipos"
      subtitle="Creá y administrá tus equipos de capas de color"
      size="lg"
      footer={<ModalFooterButtons onCancel={onClose} cancelText="Cerrar" />}
    >
      {alerta && <ModalAlert type={alerta.tipo === 'success' ? 'success' : 'error'}>{alerta.texto}</ModalAlert>}

      <div className={styles.layout}>
        {/* Left: team list + create */}
        <div className={styles.listPanel}>
          <div className={styles.createRow}>
            <input
              type="text"
              className={styles.input}
              placeholder="Nombre del nuevo equipo"
              value={nuevoNombre}
              onChange={(e) => setNuevoNombre(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') crearEquipo(); }}
              maxLength={100}
            />
            <button
              className="btn-tesla outline-subtle-primary sm"
              onClick={crearEquipo}
              disabled={creando || !nuevoNombre.trim()}
              aria-label="Crear equipo"
            >
              <Plus size={14} />
              {creando ? 'Creando...' : 'Crear'}
            </button>
          </div>

          <div className={styles.teamList}>
            {loadingEquipos ? (
              <ModalLoading message="Cargando equipos..." />
            ) : equiposManejables.length === 0 ? (
              <div className={styles.emptyState}>Todavía no tenés equipos. Creá el primero.</div>
            ) : (
              equiposManejables.map((eq) => (
                <button
                  key={eq.id}
                  className={`${styles.teamItem} ${selectedId === eq.id ? styles.teamItemActive : ''}`}
                  onClick={() => seleccionar(eq)}
                >
                  <Users size={14} />
                  <span className={styles.teamName}>{eq.nombre}</span>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right: selected team management */}
        <div className={styles.detailPanel}>
          {!selectedEquipo ? (
            <div className={styles.emptyDetail}>
              Seleccioná un equipo para administrar sus miembros, o creá uno nuevo.
            </div>
          ) : (
            <>
              {/* Header: name + rename/delete */}
              <div className={styles.detailHeader}>
                {renombrando ? (
                  <div className={styles.renameRow}>
                    <input
                      type="text"
                      className={styles.input}
                      value={nombreEdit}
                      onChange={(e) => setNombreEdit(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') guardarNombre(); }}
                      maxLength={100}
                      autoFocus
                    />
                    <button
                      className="btn-tesla outline-subtle-success sm"
                      onClick={guardarNombre}
                      disabled={guardandoNombre || !nombreEdit.trim()}
                      aria-label="Guardar nombre"
                    >
                      <Check size={14} />
                    </button>
                    <button
                      className="btn-tesla ghost sm"
                      onClick={() => setRenombrando(false)}
                      disabled={guardandoNombre}
                      aria-label="Cancelar"
                    >
                      <X size={14} />
                    </button>
                  </div>
                ) : (
                  <>
                    <h3 className={styles.detailTitle}>{selectedEquipo.nombre}</h3>
                    <div className={styles.detailActions}>
                      <button
                        className="btn-tesla outline-subtle-primary sm"
                        onClick={iniciarRenombrar}
                      >
                        <Pencil size={14} />
                        Renombrar
                      </button>
                      <button
                        className="btn-tesla outline-subtle-danger sm"
                        onClick={() => setConfirmarBorrado(true)}
                      >
                        <Trash2 size={14} />
                        Eliminar
                      </button>
                    </div>
                  </>
                )}
              </div>

              {confirmarBorrado && (
                <div className={styles.confirmBox}>
                  <span>¿Eliminar el equipo &quot;{selectedEquipo.nombre}&quot;?</span>
                  <div className={styles.confirmActions}>
                    <button
                      className="btn-tesla outline-subtle-danger sm"
                      onClick={eliminarEquipo}
                      disabled={borrando}
                    >
                      {borrando ? 'Eliminando...' : 'Sí, eliminar'}
                    </button>
                    <button
                      className="btn-tesla ghost sm"
                      onClick={() => setConfirmarBorrado(false)}
                      disabled={borrando}
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              )}

              {/* Members */}
              <div className={styles.membersSection}>
                <div className={styles.sectionTitle}>Miembros</div>

                {loadingMiembros ? (
                  <ModalLoading message="Cargando miembros..." />
                ) : miembros.length === 0 ? (
                  <div className={styles.emptyState}>Este equipo no tiene miembros.</div>
                ) : (
                  <div className={styles.memberList}>
                    {miembros.map((m) => (
                      <div key={m.usuario_id} className={styles.memberRow}>
                        <span className={styles.memberName}>{nombreUsuario(m.usuario_id)}</span>
                        <div className={styles.memberControls}>
                          <select
                            className={styles.selectSm}
                            value={m.rol}
                            onChange={(e) => cambiarRol(m, e.target.value)}
                            disabled={miembroBusy === m.usuario_id}
                            aria-label="Rol del miembro"
                          >
                            {ROLES.map((r) => (
                              <option key={r.value} value={r.value}>{r.label}</option>
                            ))}
                          </select>
                          <button
                            className="btn-tesla outline-subtle-danger icon-only sm"
                            onClick={() => quitarMiembro(m)}
                            disabled={miembroBusy === m.usuario_id}
                            aria-label="Quitar miembro"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Add member */}
                <div className={styles.addRow}>
                  <select
                    className={styles.select}
                    value={nuevoMiembroId}
                    onChange={(e) => setNuevoMiembroId(e.target.value)}
                    aria-label="Usuario a agregar"
                  >
                    <option value="">Agregar usuario...</option>
                    {usuariosDisponibles.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.nombre || u.username}
                      </option>
                    ))}
                  </select>
                  <select
                    className={styles.selectSm}
                    value={nuevoMiembroRol}
                    onChange={(e) => setNuevoMiembroRol(e.target.value)}
                    aria-label="Rol del nuevo miembro"
                  >
                    {ROLES.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                  <button
                    className="btn-tesla outline-subtle-primary sm"
                    onClick={agregarMiembro}
                    disabled={agregando || !nuevoMiembroId}
                  >
                    <Plus size={14} />
                    {agregando ? 'Agregando...' : 'Agregar'}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </ModalTesla>
  );
}
