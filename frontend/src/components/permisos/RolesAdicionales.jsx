import { useEffect, useState } from 'react';
import api from '../../services/api';
import { StatusPill } from '../kit';
import styles from './RolesAdicionales.module.css';

const detalleError = (error, fallback) => error?.response?.data?.detail || fallback;

/**
 * A user's additional roles: they only add their base permissions on top of
 * the primary role (identity — superadmin, full brand view — stays on the
 * primary one). Backed by `GET`/`PUT /usuarios/{id}/roles-adicionales`; the PUT
 * replaces the whole set. SUPERADMIN and the user's primary role are not
 * offered (the backend rejects them with 400).
 *
 * Mount it keyed by user (and primary role) so a switch always reloads it.
 * After a successful save it calls `onGuardado()` so the parent reloads the
 * user's permissions.
 */
export default function RolesAdicionales({ usuarioId, roles, onGuardado }) {
  const [datos, setDatos] = useState(null);
  const [errorCarga, setErrorCarga] = useState(null);
  const [seleccion, setSeleccion] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [errorGuardado, setErrorGuardado] = useState(null);

  useEffect(() => {
    let vigente = true;
    api
      .get(`/usuarios/${usuarioId}/roles-adicionales`)
      .then((res) => {
        if (vigente) setDatos(res.data);
      })
      .catch((error) => {
        if (vigente) setErrorCarga(detalleError(error, 'No se pudieron cargar los roles adicionales'));
      });
    return () => {
      vigente = false;
    };
  }, [usuarioId]);

  const editando = seleccion !== null;
  const codigoPrincipal = datos?.rol_principal?.codigo;
  const opciones = roles.filter((rol) => rol.codigo !== 'SUPERADMIN' && rol.codigo !== codigoPrincipal);

  const iniciarEdicion = () => {
    setErrorGuardado(null);
    setSeleccion(new Set(datos.roles_adicionales.map((rol) => rol.id)));
  };

  const alternar = (rolId) => {
    setSeleccion((prev) => {
      const siguiente = new Set(prev);
      if (siguiente.has(rolId)) siguiente.delete(rolId);
      else siguiente.add(rolId);
      return siguiente;
    });
  };

  const guardar = async () => {
    setGuardando(true);
    setErrorGuardado(null);
    try {
      // Sent in the options' order so the request does not depend on click order.
      const rolIds = opciones.filter((rol) => seleccion.has(rol.id)).map((rol) => rol.id);
      const res = await api.put(`/usuarios/${usuarioId}/roles-adicionales`, { rol_ids: rolIds });
      setDatos(res.data);
      setSeleccion(null);
      onGuardado();
    } catch (error) {
      setErrorGuardado(detalleError(error, 'Error al guardar los roles adicionales'));
    } finally {
      setGuardando(false);
    }
  };

  let contenido;
  if (errorCarga) {
    contenido = (
      <p className={styles.error} role="alert">
        {errorCarga}
      </p>
    );
  } else if (!datos) {
    contenido = <span className={styles.muted}>Cargando...</span>;
  } else if (editando) {
    contenido = (
      <div className={styles.editor}>
        <fieldset className={styles.opciones} disabled={guardando}>
          <legend className={styles.srOnly}>Elegí los roles adicionales</legend>
          {opciones.map((rol) => (
            <label key={rol.id} className={styles.opcion}>
              <input
                type="checkbox"
                className={styles.checkbox}
                checked={seleccion.has(rol.id)}
                onChange={() => alternar(rol.id)}
              />
              <span>{rol.nombre}</span>
              <code className={styles.codigo}>{rol.codigo}</code>
            </label>
          ))}
        </fieldset>
        {errorGuardado && (
          <p className={styles.error} role="alert">
            {errorGuardado}
          </p>
        )}
        <div className={styles.acciones}>
          <button type="button" className="btn-tesla outline-subtle-success sm" onClick={guardar} disabled={guardando}>
            {guardando ? 'Guardando...' : 'Guardar'}
          </button>
          <button
            type="button"
            className="btn-tesla ghost sm"
            onClick={() => setSeleccion(null)}
            disabled={guardando}
          >
            Cancelar
          </button>
        </div>
      </div>
    );
  } else {
    contenido = (
      <div className={styles.resumen}>
        {datos.roles_adicionales.length === 0 ? (
          <span className={styles.muted}>Ninguno</span>
        ) : (
          datos.roles_adicionales.map((rol) => (
            <StatusPill key={rol.id} tone="neutral" variant="soft">
              {rol.nombre}
            </StatusPill>
          ))
        )}
        <button type="button" className="btn-tesla outline-subtle-primary sm" onClick={iniciarEdicion}>
          Editar roles adicionales
        </button>
      </div>
    );
  }

  return (
    <section className={styles.seccion} aria-labelledby={`roles-adicionales-${usuarioId}`}>
      <h4 id={`roles-adicionales-${usuarioId}`} className={styles.titulo}>
        Roles adicionales
      </h4>
      <p className={styles.ayuda}>Suman los permisos de su rol; no cambian el rol principal.</p>
      {contenido}
    </section>
  );
}
