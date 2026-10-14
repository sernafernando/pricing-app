import { useState, useEffect, useRef } from 'react';
import api from '../services/api';
import adminStyles from '../pages/Admin.module.css';
import FormularioRol from './roles/FormularioRol';
import ModalClonarRol from './roles/ModalClonarRol';
import ModalConfirmarEliminarRol from './roles/ModalConfirmarEliminarRol';
import MatrizRoles from './roles/MatrizRoles';
import BarraCambios from './roles/BarraCambios';
import styles from './PanelRoles.module.css';

// The backend refuses to change SUPERADMIN's permissions: it has them all.
const esSoloLectura = (rol) => rol.codigo === 'SUPERADMIN';

const FORM_ROL_VACIO = { codigo: '', nombre: '', descripcion: '', orden: 0 };
const CLONAR_VACIO = { nuevo_codigo: '', nuevo_nombre: '', descripcion: '' };

/** Drops pending cells that already match what is saved for their role. */
function podarPendientes(pendientes, permisosPorRol) {
  const resultado = {};
  for (const [rolId, cambios] of Object.entries(pendientes)) {
    const base = permisosPorRol[rolId];
    if (!base) continue;
    const vigentes = Object.entries(cambios).filter(([codigo, valor]) => base.includes(codigo) !== valor);
    if (vigentes.length > 0) resultado[rolId] = Object.fromEntries(vigentes);
  }
  return resultado;
}

export default function PanelRoles() {
  const [roles, setRoles] = useState([]);
  const [catalogo, setCatalogo] = useState({});
  // Saved permission codes per role id, and unsaved cells per role id: { [rolId]: { [codigo]: boolean } }.
  const [permisosPorRol, setPermisosPorRol] = useState({});
  const [pendientes, setPendientes] = useState({});
  const [loading, setLoading] = useState(true);
  // Role create/edit/clone in flight, and matrix save in flight: independent so one never locks the other.
  const [guardando, setGuardando] = useState(false);
  const [guardandoPermisos, setGuardandoPermisos] = useState(false);
  const [mensaje, setMensaje] = useState(null);

  // Estados para crear/editar rol
  const [mostrarFormRol, setMostrarFormRol] = useState(false);
  const [editandoRol, setEditandoRol] = useState(null);
  const [formRol, setFormRol] = useState(FORM_ROL_VACIO);

  // Estado para eliminar rol
  const [rolAEliminar, setRolAEliminar] = useState(null);
  const [eliminando, setEliminando] = useState(false);

  // Estado para clonar rol (rolAClonar abre el modal)
  const [rolAClonar, setRolAClonar] = useState(null);
  const [clonarData, setClonarData] = useState(CLONAR_VACIO);

  const mensajeTimerRef = useRef(null);

  useEffect(() => {
    cargarDatos();
    // Mount-only load: later reloads are explicit (after a save or a role change).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => clearTimeout(mensajeTimerRef.current), []);

  const mostrarMensaje = (nuevo) => {
    clearTimeout(mensajeTimerRef.current);
    setMensaje(nuevo);
    if (nuevo?.tipo === 'success') {
      mensajeTimerRef.current = setTimeout(() => setMensaje(null), 3000);
    }
  };

  const cargarPermisosRoles = async (listaRoles) => {
    const editables = listaRoles.filter((rol) => !esSoloLectura(rol));
    const respuestas = await Promise.all(editables.map((rol) => api.get(`/roles/${rol.id}/permisos`)));
    const base = Object.fromEntries(
      editables.map((rol, i) => [rol.id, respuestas[i].data.permisos.map((p) => p.codigo)]),
    );
    setPermisosPorRol(base);
    setPendientes((prev) => podarPendientes(prev, base));
  };

  const cargarDatos = async () => {
    try {
      const [rolesRes, catalogoRes] = await Promise.all([
        api.get('/roles'),
        api.get('/permisos/catalogo')
      ]);

      setRoles(rolesRes.data);
      setCatalogo(catalogoRes.data || {});
      await cargarPermisosRoles(rolesRes.data);
    } catch (error) {
      console.error('Error cargando datos:', error);
      mostrarMensaje({ tipo: 'error', texto: `Error al cargar datos: ${error.response?.data?.detail || error.message}` });
    } finally {
      setLoading(false);
    }
  };

  const tienePermiso = (rol, codigo) => {
    if (esSoloLectura(rol)) return true;
    const pendiente = pendientes[rol.id]?.[codigo];
    return pendiente ?? (permisosPorRol[rol.id] || []).includes(codigo);
  };

  const esPendiente = (rol, codigo) => pendientes[rol.id]?.[codigo] !== undefined;

  const togglePermiso = (rol, codigo) => {
    if (esSoloLectura(rol) || guardandoPermisos) return;
    const nuevo = !tienePermiso(rol, codigo);
    const guardado = (permisosPorRol[rol.id] || []).includes(codigo);
    setPendientes((prev) => {
      const cambios = { ...prev[rol.id] };
      if (nuevo === guardado) delete cambios[codigo];
      else cambios[codigo] = nuevo;
      const siguiente = { ...prev };
      if (Object.keys(cambios).length > 0) siguiente[rol.id] = cambios;
      else delete siguiente[rol.id];
      return siguiente;
    });
  };

  const cantidadPendientes = Object.values(pendientes).reduce((total, cambios) => total + Object.keys(cambios).length, 0);

  /** The role's full resulting set: the PUT replaces every permission of the role. */
  const permisosResultantes = (rol) => {
    const codigos = new Set(permisosPorRol[rol.id] || []);
    for (const [codigo, valor] of Object.entries(pendientes[rol.id] || {})) {
      if (valor) codigos.add(codigo);
      else codigos.delete(codigo);
    }
    return [...codigos].sort();
  };

  const guardarCambios = async () => {
    const sucios = roles.filter((rol) => !esSoloLectura(rol) && pendientes[rol.id]);
    if (sucios.length === 0) return;

    setGuardandoPermisos(true);
    const resultados = await Promise.allSettled(
      sucios.map((rol) => api.put(`/roles/${rol.id}/permisos`, { permisos: permisosResultantes(rol) })),
    );
    const guardados = new Set(sucios.filter((_, i) => resultados[i].status === 'fulfilled').map((rol) => String(rol.id)));
    setPendientes((prev) => Object.fromEntries(Object.entries(prev).filter(([rolId]) => !guardados.has(rolId))));
    const fallo = resultados.find((r) => r.status === 'rejected');

    try {
      await cargarPermisosRoles(roles);
      if (fallo) {
        console.error('Error guardando permisos:', fallo.reason);
        mostrarMensaje({ tipo: 'error', texto: fallo.reason?.response?.data?.detail || 'Error al guardar permisos' });
      } else {
        mostrarMensaje({ tipo: 'success', texto: 'Permisos guardados correctamente' });
      }
    } catch (error) {
      console.error('Error recargando permisos de los roles:', error);
      mostrarMensaje({ tipo: 'error', texto: 'Permisos guardados, pero no se pudieron recargar. Actualizá la página.' });
    } finally {
      setGuardandoPermisos(false);
    }
  };

  const crearRol = async () => {
    if (!formRol.codigo || !formRol.nombre) {
      mostrarMensaje({ tipo: 'error', texto: 'Codigo y nombre son requeridos' });
      return;
    }

    setGuardando(true);
    try {
      await api.post('/roles', formRol);

      mostrarMensaje({ tipo: 'success', texto: 'Rol creado correctamente' });
      setMostrarFormRol(false);
      setFormRol(FORM_ROL_VACIO);
      cargarDatos();
    } catch (error) {
      console.error('Error creando rol:', error);
      mostrarMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al crear rol' });
    } finally {
      setGuardando(false);
    }
  };

  const actualizarRol = async () => {
    if (!editandoRol) return;

    setGuardando(true);
    try {
      await api.patch(`/roles/${editandoRol.id}`, {
        nombre: formRol.nombre,
        descripcion: formRol.descripcion,
        orden: formRol.orden
      });

      mostrarMensaje({ tipo: 'success', texto: 'Rol actualizado correctamente' });
      setEditandoRol(null);
      setFormRol(FORM_ROL_VACIO);
      cargarDatos();
    } catch (error) {
      console.error('Error actualizando rol:', error);
      mostrarMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al actualizar rol' });
    } finally {
      setGuardando(false);
    }
  };

  const pedirEliminarRol = (rol) => {
    if (rol.es_sistema) {
      mostrarMensaje({ tipo: 'error', texto: 'No se pueden eliminar roles de sistema' });
      return;
    }
    setRolAEliminar(rol);
  };

  const eliminarRol = async () => {
    const rol = rolAEliminar;
    setEliminando(true);
    try {
      await api.delete(`/roles/${rol.id}`);

      mostrarMensaje({ tipo: 'success', texto: 'Rol eliminado correctamente' });
      setPendientes((prev) => Object.fromEntries(Object.entries(prev).filter(([rolId]) => rolId !== String(rol.id))));
      cargarDatos();
    } catch (error) {
      console.error('Error eliminando rol:', error);
      mostrarMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al eliminar rol' });
    } finally {
      setEliminando(false);
      setRolAEliminar(null);
    }
  };

  const clonarRol = async () => {
    if (!rolAClonar || !clonarData.nuevo_codigo || !clonarData.nuevo_nombre) {
      mostrarMensaje({ tipo: 'error', texto: 'Codigo y nombre son requeridos' });
      return;
    }

    setGuardando(true);
    try {
      await api.post(`/roles/${rolAClonar.id}/clonar`, clonarData);

      mostrarMensaje({ tipo: 'success', texto: 'Rol clonado correctamente' });
      setRolAClonar(null);
      setClonarData(CLONAR_VACIO);
      cargarDatos();
    } catch (error) {
      console.error('Error clonando rol:', error);
      mostrarMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al clonar rol' });
    } finally {
      setGuardando(false);
    }
  };

  const iniciarEdicion = (rol) => {
    setEditandoRol(rol);
    setFormRol({
      codigo: rol.codigo,
      nombre: rol.nombre,
      descripcion: rol.descripcion || '',
      orden: rol.orden
    });
    setMostrarFormRol(true);
  };

  if (loading) {
    return (
      <div className={adminStyles.section}>
        <div style={{ textAlign: 'center', padding: '40px' }}>
          Cargando roles y permisos...
        </div>
      </div>
    );
  }

  return (
    <div>
      {mensaje && (
        <div role="status" className={mensaje.tipo === 'success' ? styles.mensajeExito : styles.mensajeError}>
          {mensaje.texto}
        </div>
      )}

      <div className={styles.layout}>
        {/* Roles: alta, edición, clonado y baja (pasan a un panel lateral en T4b) */}
        <div className={adminStyles.section}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0 }}>Roles</h3>
            <button
              onClick={() => {
                setMostrarFormRol(true);
                setEditandoRol(null);
                setFormRol({ ...FORM_ROL_VACIO, orden: roles.length });
              }}
              className="btn-tesla outline-subtle-primary sm"
            >
              + Nuevo Rol
            </button>
          </div>

          {/* Form crear/editar rol */}
          {mostrarFormRol && (
            <FormularioRol
              form={formRol}
              onChange={setFormRol}
              esEdicion={!!editandoRol}
              guardando={guardando}
              onGuardar={editandoRol ? actualizarRol : crearRol}
              onCancelar={() => {
                setMostrarFormRol(false);
                setEditandoRol(null);
                setFormRol(FORM_ROL_VACIO);
              }}
            />
          )}

          {/* Lista de roles */}
          <div className={styles.listaRoles}>
            {roles.map(rol => (
              <div key={rol.id} className={styles.tarjetaRol}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-primary)' }}>
                      {rol.nombre}
                      {rol.es_sistema && (
                        <span style={{
                          fontSize: '10px',
                          padding: '2px 6px',
                          background: 'var(--warning-bg)',
                          color: 'var(--warning-text)',
                          borderRadius: '4px'
                        }}>
                          SISTEMA
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {rol.codigo} - {rol.usuarios_count || 0} usuarios
                    </div>
                  </div>
                  <div className={styles.accionesRol}>
                    {!esSoloLectura(rol) && (
                      <button
                        onClick={() => setRolAClonar(rol)}
                        aria-label={`Clonar ${rol.nombre}`}
                        className="btn-tesla ghost sm"
                      >
                        Clonar
                      </button>
                    )}
                    {!rol.es_sistema && (
                      <>
                        <button
                          onClick={() => iniciarEdicion(rol)}
                          title="Editar"
                          style={{
                            padding: '4px 8px',
                            background: 'var(--info-bg)',
                            color: 'var(--info-text)',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '12px'
                          }}
                        >
                          Editar
                        </button>
                        <button
                          onClick={() => pedirEliminarRol(rol)}
                          title="Eliminar"
                          style={{
                            padding: '4px 8px',
                            background: 'var(--error-bg)',
                            color: 'var(--error-text)',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '12px'
                          }}
                        >
                          X
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {rol.descripcion && (
                  <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                    {rol.descripcion}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Matriz roles x permisos */}
        <section className={adminStyles.section} aria-label="Permisos por rol">
          <h3 className={styles.titulo}>Permisos por rol</h3>
          <MatrizRoles
            catalogo={catalogo}
            roles={roles}
            esSoloLectura={esSoloLectura}
            tienePermiso={tienePermiso}
            esPendiente={esPendiente}
            onToggle={togglePermiso}
            deshabilitado={guardandoPermisos}
          />
          <BarraCambios
            cantidad={cantidadPendientes}
            guardando={guardandoPermisos}
            onDescartar={() => setPendientes({})}
            onGuardar={guardarCambios}
          />
        </section>
      </div>

      {rolAClonar && (
        <ModalClonarRol
          rol={rolAClonar}
          datos={clonarData}
          onChange={setClonarData}
          guardando={guardando}
          onClonar={clonarRol}
          onCancelar={() => {
            setRolAClonar(null);
            setClonarData(CLONAR_VACIO);
          }}
        />
      )}

      {rolAEliminar && (
        <ModalConfirmarEliminarRol
          rol={rolAEliminar}
          eliminando={eliminando}
          onConfirmar={eliminarRol}
          onCancelar={() => setRolAEliminar(null)}
        />
      )}
    </div>
  );
}
