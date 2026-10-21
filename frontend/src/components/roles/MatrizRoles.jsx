import { useState, useEffect, useRef } from 'react';
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

function claseCelda({ pendiente, seleccionada, concedida }) {
  return [
    pendiente ? styles.pendiente : styles.celda,
    seleccionada && styles.celdaSeleccionada,
    seleccionada && concedida && styles.celdaConcedida,
  ].filter(Boolean).join(' ');
}

/**
 * Scrolls `scroller` horizontally (never the page) so the selected header is in
 * view, clear of the sticky "Permiso" column on the left. No-op when visible.
 * Measures live rects: the sticky cell's right edge is where the view really starts.
 */
function mostrarColumnaSeleccionada(scroller) {
  const th = scroller?.querySelector('th[aria-current="true"]');
  const fija = scroller?.querySelector('thead th');
  if (!th || !fija || typeof scroller.scrollTo !== 'function') return;
  const columna = th.getBoundingClientRect();
  const inicioVisible = fija.getBoundingClientRect().right;
  const finVisible = scroller.getBoundingClientRect().left + scroller.clientWidth;
  let desplazamiento = 0;
  if (columna.left < inicioVisible) desplazamiento = columna.left - inicioVisible;
  else if (columna.right > finVisible) desplazamiento = columna.right - finVisible;
  if (desplazamiento !== 0) {
    scroller.scrollTo({ left: Math.max(0, scroller.scrollLeft + desplazamiento), behavior: 'smooth' });
  }
}

function mensajeVacio(q, soloDelRol) {
  if (q) return 'No hay permisos que coincidan.';
  if (soloDelRol) return 'Este rol no tiene permisos.';
  return 'No hay permisos para mostrar.';
}

/**
 * Roles x permissions matrix: one row per catalog permission (grouped by
 * category), one checkbox column per role. Purely presentational: the cell
 * state, the pending mark and the toggle come from `PanelRoles`. A role whose
 * saved permissions could not be loaded (`sinCargar`) gets a locked column.
 *
 * `rolSeleccionado` (the role open in the drawer, or null) gets a highlighted
 * column, and a "Solo los permisos de este rol" toggle (`soloDelRol`) that keeps
 * only the rows it has, pending changes included (same `tienePermiso` as the cells).
 */
export default function MatrizRoles({
  catalogo, roles, esSoloLectura, tienePermiso, esPendiente, sinCargar, onToggle, deshabilitado,
  rolSeleccionado = null, soloDelRol = false, onSoloDelRolChange,
}) {
  const [busqueda, setBusqueda] = useState('');
  const scrollRef = useRef(null);
  const rolSeleccionadoId = rolSeleccionado?.id ?? null;

  // A role whose permissions are unknown cannot be filtered by them.
  const filtrable = rolSeleccionado !== null && !sinCargar(rolSeleccionado);
  const filtrando = filtrable && soloDelRol;
  const delRol = (p) => tienePermiso(rolSeleccionado, p.codigo);
  const cantidadDelRol = filtrable
    ? Object.values(catalogo || {}).flat().filter(delRol).length
    : 0;

  const q = normalizar(busqueda).trim();
  const grupos = Object.entries(catalogo || {})
    .map(([categoria, permisos]) => ({
      categoria,
      nombre: nombreCategoria(categoria),
      // A row the role has a pending change on stays while filtering, so an uncheck can be seen and undone.
      visibles: (permisos || []).filter(
        (p) => coincide(p, q) && (!filtrando || delRol(p) || esPendiente(rolSeleccionado, p.codigo)),
      ),
    }))
    .filter((grupo) => grupo.visibles.length > 0);
  const hayFilas = grupos.length > 0;

  // Re-runs when the table mounts again (a search or the filter left no rows), so a role
  // selected meanwhile still gets its column scrolled into view.
  useEffect(() => {
    if (rolSeleccionadoId !== null && hayFilas) mostrarColumnaSeleccionada(scrollRef.current);
  }, [rolSeleccionadoId, hayFilas]);

  return (
    <div className={styles.wrapper}>
      <SearchInput
        value={busqueda}
        onChange={setBusqueda}
        placeholder="Buscá un permiso por código o nombre…"
        size="sm"
        className={styles.search}
      />

      {filtrable && (
        <label className={styles.soloRol}>
          <input
            type="checkbox"
            className={styles.casilla}
            checked={soloDelRol}
            onChange={(e) => onSoloDelRolChange(e.target.checked)}
          />
          Solo los permisos de este rol ({cantidadDelRol})
        </label>
      )}

      {!hayFilas ? (
        <div className={styles.vacio}>{mensajeVacio(q, filtrando)}</div>
      ) : (
        <div ref={scrollRef} className={styles.scroll}>
          <table className={styles.tabla} aria-label="Matriz de roles y permisos">
            <thead>
              <tr>
                <th scope="col" className={styles.colPermiso}>Permiso</th>
                {roles.map((rol) => {
                  const seleccionado = rol.id === rolSeleccionado?.id;
                  return (
                    <th
                      key={rol.id}
                      scope="col"
                      className={seleccionado ? styles.colRolSeleccionado : styles.colRol}
                      title={tituloColumna(rol, esSoloLectura(rol), sinCargar(rol))}
                      aria-current={seleccionado ? 'true' : undefined}
                    >
                      {rol.nombre}
                      {seleccionado && <>{' '}<span className={styles.srOnly}>(seleccionado)</span></>}
                    </th>
                  );
                })}
              </tr>
            </thead>
            {grupos.map((grupo) => (
              <tbody key={grupo.categoria}>
                <tr>
                  <th scope="colgroup" colSpan={roles.length + 1} className={styles.categoria}>
                    <span className={styles.categoriaEtiqueta}>{grupo.nombre}</span>
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
                      const concedida = tienePermiso(rol, permiso.codigo);
                      const seleccionada = rol.id === rolSeleccionado?.id;
                      return (
                        <td key={rol.id} className={claseCelda({ pendiente, seleccionada, concedida })}>
                          <input
                            type="checkbox"
                            className={styles.casilla}
                            aria-label={`${permiso.nombre} para ${rol.nombre}`}
                            checked={concedida}
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
