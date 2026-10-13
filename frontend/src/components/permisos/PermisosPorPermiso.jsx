import { useState } from 'react';
import SearchInput from '../SearchInput';
import { nombreCategoria } from '../../registry/screenCatalog';
import { normalizar } from '../../registry/permisosAcceso';
import { FilaPermiso } from './PermisosPorPantalla';
import useAccionesOverride from './useAccionesOverride';
import styles from './PermisosPorPermiso.module.css';

function coincide(permiso, q) {
  return !q || `${normalizar(permiso.codigo)} ${normalizar(permiso.nombre)}`.includes(q);
}

/**
 * "Por permiso" view of one user's permissions: every permission of the
 * `GET /permisos/usuario/{id}` payload grouped by its category, with its
 * effective state, origin and the same Conceder / Quitar / Resetear actions
 * (and `onActualizado` / `onMensaje` contract) as `PermisosPorPantalla`.
 */
export default function PermisosPorPermiso({ usuarioId, permisosUsuario, onActualizado, onMensaje, bloqueo }) {
  const [busqueda, setBusqueda] = useState('');
  const acciones = useAccionesOverride({ usuarioId, rol: permisosUsuario?.rol, onActualizado, onMensaje, bloqueo });

  const q = normalizar(busqueda).trim();
  const grupos = Object.entries(permisosUsuario?.permisos_detallados || {})
    .map(([categoria, permisos]) => ({
      categoria,
      nombre: nombreCategoria(categoria),
      total: (permisos || []).length,
      concedidos: (permisos || []).filter((p) => p.efectivo).length,
      visibles: (permisos || []).filter((p) => coincide(p, q)),
    }))
    .filter((grupo) => grupo.visibles.length > 0);

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <SearchInput
          value={busqueda}
          onChange={setBusqueda}
          placeholder="Buscá un permiso por código o nombre…"
          size="sm"
          className={styles.search}
        />
      </div>

      <div className={styles.lista}>
        {grupos.length === 0 && <div className={styles.vacio}>No hay permisos que coincidan.</div>}

        {grupos.map((grupo) => (
          <section key={grupo.categoria} className={styles.grupo} aria-label={grupo.nombre}>
            <header className={styles.grupoHeader}>
              <h3 className={styles.grupoTitulo}>{grupo.nombre}</h3>
              <span className={styles.grupoConteo}>
                {grupo.concedidos} de {grupo.total} concedidos
              </span>
            </header>
            <ul className={styles.detalleLista}>
              {grupo.visibles.map((permiso) => (
                <FilaPermiso key={permiso.codigo} permiso={permiso} acciones={acciones} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
