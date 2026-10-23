import { useId, useState } from 'react';
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

const comparaTexto = (a, b) => normalizar(a).localeCompare(normalizar(b), 'es');
const porNombre = (a, b) => comparaTexto(a.nombre, b.nombre);

/** Sort criteria; ties on role and status fall back to the name. */
const ORDENES = [
  { valor: 'id', etiqueta: 'ID (creación)', comparar: (a, b) => a.id - b.id },
  { valor: 'nombre', etiqueta: 'Nombre', comparar: porNombre },
  { valor: 'username', etiqueta: 'Usuario', comparar: (a, b) => comparaTexto(a.username, b.username) },
  { valor: 'rol', etiqueta: 'Rol', comparar: (a, b) => comparaTexto(a.rol, b.rol) || porNombre(a, b) },
  { valor: 'estado', etiqueta: 'Estado', comparar: (a, b) => Number(b.activo) - Number(a.activo) || porNombre(a, b) },
];

/**
 * Left column of the Usuarios tab: searchable, sortable user list with a role chip per
 * user. The overrides chip (`+agregados −quitados`) is shown only for the
 * selected user: `GET /usuarios` carries no override data, and counting it
 * for everyone would take one permissions request per user.
 */
export default function ListaUsuarios({ usuarios, seleccionadoId, overridesSeleccionado, onSeleccionar }) {
  const [busqueda, setBusqueda] = useState('');
  const ordenId = useId();
  const [orden, setOrden] = useState('id');
  const [descendente, setDescendente] = useState(false);
  const { comparar } = ORDENES.find((o) => o.valor === orden);
  const visibles = usuarios
    .filter((usuario) => coincide(usuario, busqueda))
    .sort((a, b) => (descendente ? -comparar(a, b) : comparar(a, b)));

  return (
    <div className={styles.wrapper}>
      <SearchInput value={busqueda} onChange={setBusqueda} placeholder="Buscar usuario..." size="sm" />

      <div className={styles.orden}>
        <label className={styles.ordenEtiqueta} htmlFor={ordenId}>
          Ordenar por
        </label>
        <select
          id={ordenId}
          className={styles.ordenSelect}
          value={orden}
          onChange={(e) => setOrden(e.target.value)}
        >
          {ORDENES.map((o) => (
            <option key={o.valor} value={o.valor}>
              {o.etiqueta}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={styles.ordenSentido}
          aria-label={descendente ? 'Orden descendente' : 'Orden ascendente'}
          title="Invertir el orden"
          onClick={() => setDescendente((d) => !d)}
        >
          {descendente ? '↓' : '↑'}
        </button>
      </div>

      <ul className={styles.lista} aria-label="Usuarios del sistema">
        {visibles.length === 0 && (
          <li className={styles.vacio}>{busqueda.trim() ? 'Ningún usuario coincide.' : 'No hay usuarios.'}</li>
        )}
        {visibles.map((usuario) => {
          const seleccionado = usuario.id === seleccionadoId;
          const overrides = seleccionado ? overridesSeleccionado : null;
          return (
            <li key={usuario.id}>
              <button
                type="button"
                className={`${styles.fila} ${seleccionado ? styles.seleccionado : ''} ${
                  !usuario.activo ? styles.inactivo : ''
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
                  {!usuario.activo && <StatusPill tone="danger">Inactivo</StatusPill>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
