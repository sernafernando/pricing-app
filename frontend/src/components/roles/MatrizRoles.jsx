import { useState } from 'react';
import SearchInput from '../SearchInput';
import { nombreCategoria } from '../../registry/screenCatalog';
import { normalizar } from '../../registry/permisosAcceso';
import styles from './MatrizRoles.module.css';

function coincide(permiso, q) {
  return !q || `${normalizar(permiso.codigo)} ${normalizar(permiso.nombre)}`.includes(q);
}

const AVISO_SIN_CARGAR = 'No se pudieron cargar los permisos de este rol';

function tituloColumna(rol, soloLectura, noCargado) {
  if (soloLectura) return `${rol.nombre} tiene todos los permisos (solo lectura)`;
  if (noCargado) return AVISO_SIN_CARGAR;
  return rol.codigo;
}

/**
 * Roles x permissions matrix: one row per catalog permission (grouped by
 * category), one checkbox column per role. Purely presentational: the cell
 * state, the pending mark and the toggle come from `PanelRoles`. A role whose
 * saved permissions could not be loaded (`sinCargar`) gets a locked column.
 */
export default function MatrizRoles({
  catalogo, roles, esSoloLectura, tienePermiso, esPendiente, sinCargar, onToggle, deshabilitado,
}) {
  const [busqueda, setBusqueda] = useState('');

  const q = normalizar(busqueda).trim();
  const grupos = Object.entries(catalogo || {})
    .map(([categoria, permisos]) => ({
      categoria,
      nombre: nombreCategoria(categoria),
      visibles: (permisos || []).filter((p) => coincide(p, q)),
    }))
    .filter((grupo) => grupo.visibles.length > 0);

  return (
    <div className={styles.wrapper}>
      <SearchInput
        value={busqueda}
        onChange={setBusqueda}
        placeholder="Buscá un permiso por código o nombre…"
        size="sm"
        className={styles.search}
      />

      {grupos.length === 0 ? (
        <div className={styles.vacio}>
          {q ? 'No hay permisos que coincidan.' : 'No hay permisos para mostrar.'}
        </div>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.tabla} aria-label="Matriz de roles y permisos">
            <thead>
              <tr>
                <th scope="col" className={styles.colPermiso}>Permiso</th>
                {roles.map((rol) => (
                  <th
                    key={rol.id}
                    scope="col"
                    className={styles.colRol}
                    title={tituloColumna(rol, esSoloLectura(rol), sinCargar(rol))}
                  >
                    {rol.nombre}
                  </th>
                ))}
              </tr>
            </thead>
            {grupos.map((grupo) => (
              <tbody key={grupo.categoria}>
                <tr>
                  <th scope="colgroup" colSpan={roles.length + 1} className={styles.categoria}>
                    {grupo.nombre}
                  </th>
                </tr>
                {grupo.visibles.map((permiso) => (
                  <tr key={permiso.codigo} className={styles.fila}>
                    <th scope="row" className={styles.permiso}>
                      <div className={styles.permisoContenido}>
                        <span className={styles.permisoNombre}>
                          {permiso.nombre}
                          {permiso.es_critico && <span className={styles.critico}>Crítico</span>}
                        </span>
                        <code className={styles.codigo}>{permiso.codigo}</code>
                      </div>
                    </th>
                    {roles.map((rol) => {
                      const soloLectura = esSoloLectura(rol);
                      const noCargado = sinCargar(rol);
                      const pendiente = esPendiente(rol, permiso.codigo);
                      return (
                        <td key={rol.id} className={pendiente ? styles.pendiente : styles.celda}>
                          <input
                            type="checkbox"
                            className={styles.casilla}
                            aria-label={`${permiso.nombre} para ${rol.nombre}`}
                            checked={tienePermiso(rol, permiso.codigo)}
                            onChange={() => onToggle(rol, permiso.codigo)}
                            title={noCargado ? AVISO_SIN_CARGAR : undefined}
                            disabled={deshabilitado || soloLectura || noCargado}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </div>
  );
}
