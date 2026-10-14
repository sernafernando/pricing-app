import styles from './DetalleRol.module.css';

/**
 * Role detail inside the role drawer, plus its management actions. System roles
 * cannot be edited or deleted; SUPERADMIN (`soloLectura`) cannot be cloned.
 * `cantidadPermisos` is the saved count, or null when it could not be loaded.
 * `bloqueado` disables the actions while a matrix save is in flight.
 */
export default function DetalleRol({ rol, soloLectura, cantidadPermisos, bloqueado, onEditar, onClonar, onEliminar }) {
  let permisos = cantidadPermisos ?? 'Sin cargar';
  if (soloLectura) permisos = 'Todos';

  return (
    <>
      {rol.es_sistema && <span className={styles.badgeSistema}>SISTEMA</span>}
      <dl className={styles.datos}>
        <dt>Código</dt>
        <dd>{rol.codigo}</dd>
        <dt>Descripción</dt>
        <dd>{rol.descripcion || 'Sin descripción'}</dd>
        <dt>Usuarios</dt>
        <dd>{rol.usuarios_count || 0}</dd>
        <dt>Permisos</dt>
        <dd>{permisos}</dd>
      </dl>
      <div className={styles.acciones}>
        {!rol.es_sistema && (
          <button type="button" onClick={onEditar} disabled={bloqueado} className="btn-tesla outline-subtle-primary sm">
            Editar
          </button>
        )}
        {!soloLectura && (
          <button
            type="button"
            onClick={onClonar}
            disabled={bloqueado}
            aria-label={`Clonar ${rol.nombre}`}
            className="btn-tesla ghost sm"
          >
            Clonar
          </button>
        )}
        {!rol.es_sistema && (
          <button type="button" onClick={onEliminar} disabled={bloqueado} className="btn-tesla outline-subtle-danger sm">
            Eliminar rol
          </button>
        )}
      </div>
      {rol.es_sistema && (
        <p className={styles.nota}>
          {soloLectura
            ? 'Es un rol de sistema con todos los permisos: no se puede modificar.'
            : 'Es un rol de sistema: no se puede editar ni eliminar. Sus permisos se cambian desde la matriz.'}
        </p>
      )}
    </>
  );
}
