import { ChevronRight } from 'lucide-react';
import { SegmentedControl } from '../../kit';
import { NO_GROUP } from '../groupNodes';
import styles from './StockAudit.module.css';

/**
 * The Auditoría de stock's "Ver por" (auditoria-stock-niveles S1): the table's top level -- Marca (the default),
 * Categoría or Producto -- and, after drilling into a brand or a category, the way back up. Every change goes to
 * the URL through `onChange` (`setFilters` updates): picking a level leaves any drill. `names` (the audit's
 * `grupo_nombres`) names the drilled brand and category as their rows show them; the key until it arrives.
 */
const LEVELS = [
  { value: 'marca', label: 'Marca' },
  { value: 'categoria', label: 'Categoría' },
  { value: 'producto', label: 'Producto' },
];

const NO_DRILL = { grupo_marca: '', grupo_categoria: '' };
// The URL keeps Marca as the absence of `nivel`.
const levelUpdate = (nivel) => ({ nivel: nivel === 'marca' ? '' : nivel });

const brandLabel = (key, name) => (key === NO_GROUP ? 'Sin marca' : name || key);
const categoryLabel = (key, name) => (key === NO_GROUP ? 'Sin categoría' : name || key);

function Crumb({ label, onClick }) {
  return (
    <>
      <button type="button" className={styles.crumb} onClick={onClick}>
        {label}
      </button>
      <ChevronRight size={12} aria-hidden="true" className={styles.crumbSep} />
    </>
  );
}

export default function AuditLevelBar({ filters, onChange, names }) {
  const { nivel, grupo_marca: brand, grupo_categoria: category } = filters;
  const drilled = Boolean(brand || category);
  return (
    <div className={styles.levelBar}>
      <span className={styles.levelLabel}>Ver por</span>
      <SegmentedControl
        label="Ver por"
        options={LEVELS}
        value={nivel}
        onChange={(value) => onChange({ ...levelUpdate(value), ...NO_DRILL })}
      />
      {drilled && (
        <nav className={styles.crumbs} aria-label="Nivel de la auditoría">
          {brand ? (
            <Crumb label="Todas las marcas" onClick={() => onChange({ ...levelUpdate('marca'), ...NO_DRILL })} />
          ) : (
            <Crumb label="Todas las categorías" onClick={() => onChange({ ...levelUpdate('categoria'), ...NO_DRILL })} />
          )}
          {brand && category && (
            <Crumb label={brandLabel(brand, names?.marca)} onClick={() => onChange({ ...levelUpdate('categoria'), grupo_marca: brand, grupo_categoria: '' })} />
          )}
          <span className={styles.crumbCurrent} aria-current="page">
            {category ? categoryLabel(category, names?.categoria) : brandLabel(brand, names?.marca)}
          </span>
        </nav>
      )}
    </div>
  );
}
