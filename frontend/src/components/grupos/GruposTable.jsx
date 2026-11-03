import { resumenFiltro } from './grupoFormat';
import styles from '../sellIn/SellInTable.module.css';

const anuladasTexto = (n) => (n === 1 ? '1 anulada' : `${n} anuladas`);

/**
 * The offset groups (`useGrupos`): name and description, one line per filter row (a group reaches a product
 * matching ANY row), how many products they reach and the sell-out campaigns using them. "Editar" opens one.
 */
export default function GruposTable({ grupos, subcategorias, selectedId, onSelect }) {
  return (
    <div className={styles.scroller}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Grupo</th>
            <th>Filtros</th>
            <th className={styles.num}>Productos</th>
            <th>Campañas de sell out</th>
            <th aria-label="Acciones" />
          </tr>
        </thead>
        <tbody>
          {grupos.length === 0 && (
            <tr>
              <td colSpan={5} className={styles.empty}>
                No hay grupos.
              </td>
            </tr>
          )}
          {grupos.map((grupo) => {
            const activas = grupo.campanas.filter((c) => c.estado === 'activa');
            const anuladas = grupo.campanas.length - activas.length;
            return (
              <tr key={grupo.id} className={selectedId === grupo.id ? styles.rowSelected : ''}>
                <td>
                  <div>{grupo.nombre}</div>
                  {grupo.descripcion && <div className={styles.sub}>{grupo.descripcion}</div>}
                </td>
                <td>
                  {grupo.filtros.length === 0 ? (
                    <div className={styles.sub}>Sin filtros: no alcanza productos</div>
                  ) : (
                    grupo.filtros.map((filtro) => <div key={filtro.id}>{resumenFiltro(filtro, subcategorias)}</div>)
                  )}
                </td>
                <td className={styles.num}>{grupo.productos.toLocaleString('es-AR')}</td>
                <td>
                  {activas.map((c) => (
                    <div key={c.id}>{c.nombre}</div>
                  ))}
                  {anuladas > 0 && <div className={styles.sub}>{anuladasTexto(anuladas)}</div>}
                  {grupo.campanas.length === 0 && <div className={styles.sub}>Ninguna</div>}
                </td>
                <td>
                  <button type="button" className="btn-tesla ghost sm" onClick={() => onSelect(grupo.id)}>
                    Editar
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
