import { Loader2 } from 'lucide-react';
import styles from '../../pages/TiendaNubeReconcile.module.css';

// BANLIST sub-tab: bulk-unban bar + the banned-EAN table. Extracted verbatim
// from `TiendaNubeReconcile.jsx` (structural extraction, PR-6 pattern).
export default function BanlistTable({
  baneados,
  loadingBaneados,
  baneadosSeleccionados,
  toggleSeleccionBaneado,
  desbanearSeleccionados,
  desbanearEan,
}) {
  return (
    <div>
      {baneadosSeleccionados.size > 0 && (
        <div className={styles.banlistActionsBar}>
          <button type="button" className="btn-tesla outline-subtle-success sm" onClick={desbanearSeleccionados}>
            Desbanear seleccionados ({baneadosSeleccionados.size})
          </button>
        </div>
      )}
      {loadingBaneados ? (
        <div className={styles.loadingState}>
          <Loader2 size={24} className={styles.spinner} aria-hidden="true" />
          Cargando banlist...
        </div>
      ) : (
        <table className="table-tesla striped">
          <thead className="table-tesla-head">
            <tr>
              <th></th>
              <th>EAN</th>
              <th>Motivo</th>
              <th>Usuario</th>
              <th>Fecha</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {baneados.length === 0 ? (
              <tr>
                <td colSpan={6} className="no-data">
                  No hay EANs en la banlist
                </td>
              </tr>
            ) : (
              baneados.map((entry) => (
                <tr key={entry.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={baneadosSeleccionados.has(entry.id)}
                      onChange={() => toggleSeleccionBaneado(entry.id)}
                      aria-label={`Seleccionar ${entry.ean}`}
                    />
                  </td>
                  <td className={styles.banlistEan}>{entry.ean}</td>
                  <td>
                    {entry.motivo || <span className={styles.noLink}>—</span>}
                  </td>
                  <td>{entry.usuario_nombre}</td>
                  <td>{new Date(entry.fecha_creacion).toLocaleDateString()}</td>
                  <td>
                    <button
                      type="button"
                      className="btn-tesla outline-subtle-success xs"
                      onClick={() => desbanearEan(entry.id)}
                    >
                      Desbanear
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
