import { useState } from 'react';
import { Search } from 'lucide-react';
import styles from './UsuariosLista.module.css';

function iniciales(nombre) {
  return (nombre || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((parte) => parte[0].toUpperCase())
    .join('');
}

/**
 * UsuariosLista — searchable list of delegation targets (presentational).
 *
 * Replaces the former native `<select>`: every user is visible with their
 * grant count, so picking one is a single click. `conteosError` renders
 * "?" instead of a fake 0, same contract the old picker had.
 */
export default function UsuariosLista({
  usuarios,
  conteos,
  conteosError,
  seleccionadoId,
  onSeleccionar,
  disabled,
  aviso,
}) {
  const [busqueda, setBusqueda] = useState('');

  const termino = busqueda.trim().toLowerCase();
  const visibles = termino
    ? usuarios.filter((u) => (u.nombre || '').toLowerCase().includes(termino))
    : usuarios;

  return (
    <aside className={styles.panel} aria-label="Usuarios">
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <span className={styles.label}>Usuarios</span>
          <span className={styles.total}>{usuarios.length}</span>
        </div>
        <label className={styles.search}>
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar usuario..."
            aria-label="Buscar usuario"
            disabled={usuarios.length === 0}
          />
        </label>
      </div>

      {aviso ? (
        <p className={styles.aviso}>{aviso}</p>
      ) : (
        <ul className={styles.lista}>
          {visibles.map((u) => {
            const total = conteosError ? '?' : conteos[u.id] ?? 0;
            const activo = u.id === seleccionadoId;
            return (
              <li key={u.id}>
                <button
                  type="button"
                  className={activo ? styles.itemActivo : styles.item}
                  aria-pressed={activo}
                  aria-label={`${u.nombre} (${total})`}
                  onClick={() => onSeleccionar(u.id)}
                  disabled={disabled}
                >
                  <span className={styles.avatar} aria-hidden="true">{iniciales(u.nombre)}</span>
                  <span className={styles.nombre}>{u.nombre}</span>
                  <span className={styles.conteo} aria-hidden="true">{total}</span>
                </button>
              </li>
            );
          })}
          {visibles.length === 0 && <li className={styles.vacio}>Ningún usuario coincide.</li>}
        </ul>
      )}
    </aside>
  );
}
