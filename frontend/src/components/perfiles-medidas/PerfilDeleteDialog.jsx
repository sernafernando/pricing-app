/**
 * PerfilDeleteDialog — both delete-confirmation variants (in-use / not-in-use)
 * extracted verbatim from `AdministracionPerfilesMedidas.jsx` (structural
 * extraction, PR-6 pattern).
 */
import styles from '../../pages/AdministracionPerfilesMedidas.module.css';
import { AlertTriangle, Trash2 } from 'lucide-react';

export default function PerfilDeleteDialog({ deleteTarget, deleteError }) {
  return (
    <>
      {deleteError && <p className={styles.alertError}>{deleteError}</p>}
      {deleteTarget && (deleteTarget.categorias_en_uso ?? 0) > 0 ? (
        <>
          <div className={styles.deleteIconWrap}>
            <div className={styles.deleteIconAmber}>
              <AlertTriangle size={22} />
            </div>
          </div>
          <p className={styles.deleteBody}>
            Este perfil se viene usando en <strong>{deleteTarget.categorias_en_uso} categorías</strong>. Si lo
            borrás, esas categorías dejan de sugerir medidas y el operador va a tener que cargarlas a mano en cada
            publicación.
          </p>
          <div className={styles.affectedBlock}>
            {(deleteTarget.categorias_afectadas || []).map((cat) => (
              <span className={styles.chip} key={cat}>
                {cat}
              </span>
            ))}
            {deleteTarget.total_categorias_afectadas > (deleteTarget.categorias_afectadas || []).length && (
              <span className={styles.chipMore}>
                y {deleteTarget.total_categorias_afectadas - (deleteTarget.categorias_afectadas || []).length} más
              </span>
            )}
          </div>
          <p className={styles.deleteClosingLine}>
            Lo ya publicado en Tienda Nube no se toca: conserva las medidas con las que salió.
          </p>
        </>
      ) : (
        <>
          <div className={styles.deleteIconWrap}>
            <div className={styles.deleteIconRed}>
              <Trash2 size={22} />
            </div>
          </div>
          <p className={styles.deleteBody}>Ninguna categoría lo está usando. Se borra sin consecuencias.</p>
        </>
      )}
    </>
  );
}
