import { useState, useEffect, useRef } from 'react';
import api from '../services/api';
import adminStyles from '../pages/Admin.module.css';
import FormularioRol from './roles/FormularioRol';
import ModalClonarRol from './roles/ModalClonarRol';
import ModalConfirmarEliminarRol from './roles/ModalConfirmarEliminarRol';
import MatrizRoles from './roles/MatrizRoles';
import BarraCambios from './roles/BarraCambios';
import DrawerRol from './roles/DrawerRol';
import DetalleRol from './roles/DetalleRol';
import styles from './PanelRoles.module.css';

// The backend refuses to change SUPERADMIN's permissions: it has them all.
const esSoloLectura = (rol) => rol.codigo === 'SUPERADMIN';

const FORM_ROL_VACIO = { codigo: '', nombre: '', descripcion: '', orden: 0 };
const CLONAR_VACIO = { nuevo_codigo: '', nuevo_nombre: '', descripcion: '' };

/**
 * Drops pending cells that already match what is saved for their role. Roles in
 * `conservar` (their reload failed) keep their pending cells untouched; roles
 * with no saved state at all lose them, they cannot be edited.
 */
function podarPendientes(pendientes, permisosPorRol, conservar = new Set()) {
  const resultado = {};
  for (const [rolId, cambios] of Object.entries(pendientes)) {
    if (conservar.has(rolId)) {
      resultado[rolId] = cambios;
      continue;
    }
    const base = permisosPorRol[rolId];
    if (!base) continue;
    const vigentes = Object.entries(cambios).filter(([codigo, valor]) => base.includes(codigo) !== valor);
    if (vigentes.length > 0) resultado[rolId] = Object.fromEntries(vigentes);
  }
  return resultado;
}

const nombresDe = (lista) => lista.map((rol) => rol.nombre).join(', ');

export default function PanelRoles() {
  const [roles, setRoles] = useState([]);
  const [catalogo, setCatalogo] = useState({});
  // Saved permission codes per role id, and unsaved cells per role id: { [rolId]: { [codigo]: boolean } }.
  // A role with no entry in permisosPorRol has an UNKNOWN saved state (its GET failed), never an empty
  // one: its column is read-only and it is never saved, because the PUT replaces the whole set.
  const [permisosPorRol, setPermisosPorRol] = useState({});
  const [pendientes, setPendientes] = useState({});
  const [loading, setLoading] = useState(true);
  // Role create/edit/clone in flight, and matrix save in flight. They are mutually exclusive: while one
  // runs the other's controls are disabled, so a role reload never lands in the middle of a matrix save.
  const [guardando, setGuardando] = useState(false);
  const [guardandoPermisos, setGuardandoPermisos] = useState(false);
  const [mensaje, setMensaje] = useState(null);

  // Role drawer: the role whose detail it shows, or the create form (mostrarFormRol without editandoRol).
  const [rolAbiertoId, setRolAbiertoId] = useState(null);

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
  // Generation of the latest permissions load: an older load resolving late is ignored.
  const cargaPermisosRef = useRef(0);
  // Latest roles list fetched. The reload after a matrix save reads it instead of the `roles` its click
  // closed over: a role created meanwhile would otherwise be dropped from the matrix (locked column).
  const rolesRef = useRef([]);

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

  /**
   * Loads each editable role on its own, so one failing GET never blanks the others.
   * A failed role keeps the base it already had (if any). Returns the roles that failed.
   * Only the latest load started is applied: a superseded one changes nothing and returns [].
   */
  const cargarPermisosRoles = async (listaRoles) => {
    const generacion = ++cargaPermisosRef.current;
    const editables = listaRoles.filter((rol) => !esSoloLectura(rol));
    const respuestas = await Promise.allSettled(editables.map((rol) => api.get(`/roles/${rol.id}/permisos`)));
    if (generacion !== cargaPermisosRef.current) return [];
    const cargados = {};
    const fallidos = [];
    editables.forEach((rol, i) => {
      if (respuestas[i].status === 'fulfilled') {
        cargados[rol.id] = respuestas[i].value.data.permisos.map((p) => p.codigo);
      } else {
        console.error(`Error cargando permisos del rol ${rol.codigo}:`, respuestas[i].reason);
        fallidos.push(rol);
      }
    });
    const idsFallidos = new Set(fallidos.map((rol) => String(rol.id)));

    setPermisosPorRol((prev) => {
      const siguiente = { ...cargados };
      for (const rolId of idsFallidos) {
        if (prev[rolId]) siguiente[rolId] = prev[rolId];
      }
      return siguiente;
    });
    setPendientes((prev) => podarPendientes(prev, cargados, idsFallidos));
    return fallidos;
  };

  const cargarDatos = async () => {
    try {
      const [rolesRes, catalogoRes] = await Promise.all([
        api.get('/roles'),
        api.get('/permisos/catalogo')
      ]);

      rolesRef.current = rolesRes.data;
      setRoles(rolesRes.data);
      setCatalogo(catalogoRes.data || {});
      const fallidos = await cargarPermisosRoles(rolesRes.data);
      if (fallidos.length > 0) {
        mostrarMensaje({ tipo: 'error', texto: `No se pudieron cargar los permisos de: ${nombresDe(fallidos)}` });
      }
    } catch (error) {
      console.error('Error cargando datos:', error);
      mostrarMensaje({ tipo: 'error', texto: `Error al cargar datos: ${error.response?.data?.detail || error.message}` });
    } finally {
      setLoading(false);
    }
  };

  const gestionandoRoles = guardando || eliminando;
  const matrizBloqueada = guardandoPermisos || gestionandoRoles;

  const tienePermiso = (rol, codigo) => {
    if (esSoloLectura(rol)) return true;
    const pendiente = pendientes[rol.id]?.[codigo];
    return pendiente ?? (permisosPorRol[rol.id] || []).includes(codigo);
  };

  const esPendiente = (rol, codigo) => pendientes[rol.id]?.[codigo] !== undefined;

  const sinCargar = (rol) => !esSoloLectura(rol) && !permisosPorRol[rol.id];

  const togglePermiso = (rol, codigo) => {
    if (esSoloLectura(rol) || sinCargar(rol) || matrizBloqueada) return;
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
    const sucios = roles.filter((rol) => !esSoloLectura(rol) && !sinCargar(rol) && pendientes[rol.id]);
    if (sucios.length === 0 || matrizBloqueada) return;

    setGuardandoPermisos(true);
    const enviados = sucios.map((rol) => permisosResultantes(rol));
    const resultados = await Promise.allSettled(
      sucios.map((rol, i) => api.put(`/roles/${rol.id}/permisos`, { permisos: enviados[i] })),
    );
    const guardados = sucios.filter((_, i) => resultados[i].status === 'fulfilled');
    const noGuardados = sucios.filter((_, i) => resultados[i].status === 'rejected');
    const idsGuardados = new Set(guardados.map((rol) => String(rol.id)));

    // What was sent is now the saved state: correct even if the reload below fails.
    setPermisosPorRol((prev) => {
      const siguiente = { ...prev };
      sucios.forEach((rol, i) => {
        if (idsGuardados.has(String(rol.id))) siguiente[rol.id] = enviados[i];
      });
      return siguiente;
    });
    setPendientes((prev) => Object.fromEntries(Object.entries(prev).filter(([rolId]) => !idsGuardados.has(rolId))));

    let falloRecarga;
    try {
      falloRecarga = (await cargarPermisosRoles(rolesRef.current)).length > 0;
    } catch (error) {
      console.error('Error recargando permisos de los roles:', error);
      falloRecarga = true;
    } finally {
      setGuardandoPermisos(false);
    }

    if (noGuardados.length === 0) {
      mostrarMensaje(falloRecarga
        ? { tipo: 'error', texto: 'Permisos guardados, pero no se pudieron recargar. Actualizá la página.' }
        : { tipo: 'success', texto: 'Permisos guardados correctamente' });
      return;
    }

    const fallo = resultados.find((r) => r.status === 'rejected');
    console.error('Error guardando permisos:', fallo.reason);
    const detalle = fallo.reason?.response?.data?.detail || 'Error al guardar permisos';
    let texto = guardados.length > 0
      ? `Se guardaron los permisos de ${nombresDe(guardados)}, pero fallaron los de ${nombresDe(noGuardados)}: ${detalle}`
      : detalle;
    if (falloRecarga) texto += '. No se pudieron recargar los permisos; actualizá la página.';
    mostrarMensaje({ tipo: 'error', texto });
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
      setMostrarFormRol(false);
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
      setRolAbiertoId((abierto) => (abierto === rol.id ? null : abierto));
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

  const cerrarFormRol = () => {
    setMostrarFormRol(false);
    setEditandoRol(null);
    setFormRol(FORM_ROL_VACIO);
  };

  // While a role request is in flight or the create/edit form is open, the cards and + Nuevo Rol are
  // locked: switching would drop the request's panel or what was typed. Leave with Cancelar, X or Esc.
  const cambioDeRolBloqueado = gestionandoRoles || mostrarFormRol;

  const abrirRol = (rol) => {
    if (cambioDeRolBloqueado) return;
    cerrarFormRol();
    setRolAbiertoId(rol.id);
  };

  const abrirNuevoRol = () => {
    setRolAbiertoId(null);
    setEditandoRol(null);
    setFormRol({ ...FORM_ROL_VACIO, orden: roles.length });
    setMostrarFormRol(true);
  };

  // The drawer stays put while a role request is in flight or a dialog is open on top of it.
  const puedeCerrarDrawer = !gestionandoRoles && !rolAClonar && !rolAEliminar;

  const cerrarDrawer = () => {
    if (!puedeCerrarDrawer) return;
    cerrarFormRol();
    setRolAbiertoId(null);
  };

  const rolAbierto = roles.find((rol) => rol.id === rolAbiertoId) ?? null;
  const drawerAbierto = mostrarFormRol || rolAbierto !== null;
  let tituloDrawer = rolAbierto?.nombre;
  if (mostrarFormRol) tituloDrawer = editandoRol ? 'Editar Rol' : 'Nuevo Rol';

  if (loading) {
    return (
      <div className={adminStyles.section}>
        <div className={styles.cargando}>
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

      <div className={drawerAbierto ? styles.conDrawer : undefined}>
        <div className={styles.layout}>
          {/* Roles: cada tarjeta abre su panel lateral, donde se edita, clona o elimina */}
          <div className={adminStyles.section}>
            <div className={styles.encabezado}>
              <h3 className={styles.tituloRoles}>Roles</h3>
              <button
                onClick={abrirNuevoRol}
                disabled={guardandoPermisos || cambioDeRolBloqueado}
                className="btn-tesla outline-subtle-primary sm"
              >
                + Nuevo Rol
              </button>
            </div>

            <div className={styles.listaRoles}>
              {roles.map(rol => (
                <button
                  key={rol.id}
                  type="button"
                  className={rol.id === rolAbiertoId ? styles.tarjetaRolAbierta : styles.tarjetaRol}
                  onClick={() => abrirRol(rol)}
                  disabled={cambioDeRolBloqueado}
                  aria-haspopup="dialog"
                  aria-expanded={rol.id === rolAbiertoId}
                >
                  <span className={styles.tarjetaNombre}>
                    {rol.nombre}
                    {rol.es_sistema && <>{' '}<span className={styles.badgeSistema}>SISTEMA</span></>}
                  </span>
                  {' '}
                  <span className={styles.tarjetaMeta}>
                    {rol.codigo} · {rol.usuarios_count || 0} usuarios
                  </span>
                </button>
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
              sinCargar={sinCargar}
              onToggle={togglePermiso}
              deshabilitado={matrizBloqueada}
            />
            <BarraCambios
              cantidad={cantidadPendientes}
              guardando={guardandoPermisos}
              bloqueado={gestionandoRoles}
              onDescartar={() => setPendientes({})}
              onGuardar={guardarCambios}
            />
          </section>
        </div>

        {drawerAbierto && (
          <DrawerRol titulo={tituloDrawer} puedeCerrar={puedeCerrarDrawer} onCerrar={cerrarDrawer}>
            {mostrarFormRol ? (
              <FormularioRol
                form={formRol}
                onChange={setFormRol}
                esEdicion={!!editandoRol}
                guardando={guardando}
                bloqueado={guardandoPermisos}
                onGuardar={editandoRol ? actualizarRol : crearRol}
                onCancelar={cerrarFormRol}
              />
            ) : (
              <DetalleRol
                rol={rolAbierto}
                soloLectura={esSoloLectura(rolAbierto)}
                cantidadPermisos={permisosPorRol[rolAbierto.id]?.length ?? null}
                bloqueado={guardandoPermisos}
                onEditar={() => iniciarEdicion(rolAbierto)}
                onClonar={() => setRolAClonar(rolAbierto)}
                onEliminar={() => pedirEliminarRol(rolAbierto)}
              />
            )}
          </DrawerRol>
        )}
      </div>

      {rolAClonar && (
        <ModalClonarRol
          rol={rolAClonar}
          datos={clonarData}
          onChange={setClonarData}
          guardando={guardando}
          bloqueado={guardandoPermisos}
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
          bloqueado={guardandoPermisos}
          onConfirmar={eliminarRol}
          onCancelar={() => setRolAEliminar(null)}
        />
      )}
    </div>
  );
}
