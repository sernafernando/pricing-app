import { useState } from 'react';
import SearchInput from '../SearchInput';
import { StatusPill } from '../kit';
import { normalizar } from '../../registry/permisosAcceso';
import AvatarIniciales from './AvatarIniciales';
import styles from './ListaUsuarios.module.css';

function coincide(usuario, busqueda) {
  const q = normalizar(busqueda).trim();
  if (!q) return true;
  return [usuario.nombre, usuario.username, usuario.email, usuario.rol].some((campo) =>
    normalizar(campo).includes(q),
  );
}

/**
 * Left column of the Usuarios tab: searchable user list with a role chip per
 * user. The overrides chip (`+agregados −quitados`) is shown only for the
 * selected user: `GET /usuarios` carries no override data, and counting it
 * for everyone would take one permissions request per user.
 */
export default function ListaUsuarios({ usuarios, seleccionadoId, overridesSeleccionado, onSeleccionar }) {
  const [busqueda, setBusqueda] = useState('');
  const visibles = usuarios.filter((usuario) => coincide(usuario, busqueda));

  return (
    <div className={styles.wrapper}>
      <SearchInput value={busqueda} onChange={setBusqueda} placeholder="Buscar usuario..." size="sm" />

      <ul className={styles.lista} aria-label="Usuarios del sistema">
        {visibles.length === 0 && <li className={styles.vacio}>Ningún usuario coincide.</li>}
        {visibles.map((usuario) => {
          const seleccionado = usuario.id === seleccionadoId;
          const overrides = seleccionado ? overridesSeleccionado : null;
          return (
            <li key={usuario.id}>
              <button
                type="button"
                className={`${styles.fila} ${seleccionado ? styles.seleccionado : ''} ${
                  usuario.activo === false ? styles.inactivo : ''
                }`}
                aria-pressed={seleccionado}
                onClick={() => onSeleccionar(usuario)}
              >
                <AvatarIniciales nombre={usuario.nombre} className={styles.avatar} />
                <span className={styles.datos}>
                  <span className={styles.nombre}>{usuario.nombre}</span>
                  <span className={styles.secundario}>{usuario.email || (usuario.username ? `@${usuario.username}` : '')}</span>
                </span>
                <span className={styles.chips}>
                  {overrides && (
                    <span
                      className={`${styles.overrides} ${overrides.total ? '' : styles.overridesVacio}`}
                      title={`Overrides: ${overrides.agregados} agregados, ${overrides.quitados} quitados`}
                    >
                      {`+${overrides.agregados} −${overrides.quitados}`}
                    </span>
                  )}
                  <StatusPill tone={usuario.rol === 'SUPERADMIN' ? 'warning' : 'neutral'}>{usuario.rol}</StatusPill>
                  {usuario.activo === false && <StatusPill tone="danger">Inactivo</StatusPill>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
