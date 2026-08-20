/**
 * PerfilesTable — list/empty-state card extracted verbatim from
 * `AdministracionPerfilesMedidas.jsx` (structural extraction, PR-6 pattern).
 */
import styles from '../../pages/AdministracionPerfilesMedidas.module.css';
import { Plus, Pencil, Package, Loader2 } from 'lucide-react';

export default function PerfilesTable({ profiles, loading, loadError, canEdit, onCreate, onEdit, onDelete }) {
  return (
    <div className={styles.card}>
      {loading ? (
        <div className={styles.emptyState}>
          <Loader2 size={24} className={styles.spinner} />
          Cargando perfiles...
        </div>
      ) : loadError ? (
        <div className={styles.emptyState}>{loadError}</div>
      ) : profiles.length === 0 ? (
        <div className={styles.emptyState}>
          <Package size={44} strokeWidth={1.5} />
          <h2 className={styles.emptyHeading}>Todavía no hay perfiles</h2>
          <p className={styles.emptyBody}>
            Un perfil guarda peso y dimensiones de una caja que usás seguido. Con perfiles cargados, publicar un
            producto sin medidas es un clic en vez de cuatro campos.
          </p>
          {canEdit && (
            <button className={styles.btnPrimary} onClick={onCreate}>
              <Plus size={15} strokeWidth={2} /> Crear el primero
            </button>
          )}
        </div>
      ) : (
        <>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Perfil</th>
                <th className={styles.thNum}>Peso</th>
                <th className={styles.thNum}>Ancho</th>
                <th className={styles.thNum}>Alto</th>
                <th className={styles.thNum}>Prof.</th>
                <th>Se usa en</th>
                {canEdit && <th />}
              </tr>
            </thead>
            <tbody>
              {profiles.map((p) => (
                <tr key={p.id}>
                  <td className={styles.colNombre}>{p.name}</td>
                  <td className={styles.colNum}>{p.weight}</td>
                  <td className={styles.colNum}>{p.width}</td>
                  <td className={styles.colNum}>{p.height}</td>
                  <td className={styles.colNum}>{p.depth}</td>
                  <td>
                    {(p.categorias_en_uso ?? 0) === 0 ? (
                      <span className={styles.usoNone}>Sin uso</span>
                    ) : (
                      <span className={styles.usoPill}>
                        {p.categorias_en_uso} {p.categorias_en_uso === 1 ? 'categoría' : 'categorías'}
                      </span>
                    )}
                  </td>
                  {canEdit && (
                    <td className={styles.colActions}>
                      <button className={styles.btnGhostEdit} onClick={() => onEdit(p)}>
                        <Pencil size={13} /> Editar
                      </button>
                      <button className={styles.btnBorrar} onClick={() => onDelete(p)}>
                        Borrar
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <div className={styles.footerNote}>
            "Se usa en" cuenta las categorías que ya publicaron con ese perfil — es lo que alimenta la sugerencia
            al abrir el publicador.
          </div>
        </>
      )}
    </div>
  );
}
