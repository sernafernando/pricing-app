import { useMemo, useState } from 'react';
import { ChevronRight, Search } from 'lucide-react';
import { parKey } from '../parKey';
import styles from './MarcasAcordeon.module.css';

const SIN_TITULAR = 'Sin titular';

const CLASE_FILA = { agrega: styles.filaAgrega, quita: styles.filaQuita };

function estadoPar(key, checked, baseline) {
  const marcado = checked.has(key);
  const original = baseline.has(key);
  if (marcado && !original) return 'agrega';
  if (!marcado && original) return 'quita';
  return null;
}

/**
 * MarcasAcordeon — (marca, categoria) pairs grouped by marca (presentational).
 *
 * Owns only view state (search, expanded marcas, "solo asignado" toggle).
 * `checked`/`baseline` are Sets of `parKey` values owned by the parent; the
 * pending diff is derived here per row (added / removed) so the user sees
 * exactly what a save would change. A marca checkbox applies to the pairs
 * of that marca that are currently VISIBLE (search and toggle applied), so
 * a filtered view never touches rows the user cannot see.

 */
export default function MarcasAcordeon({ pares, checked, baseline, onToggle, onMarcarPares, disabled }) {
  const [busqueda, setBusqueda] = useState('');
  const [soloAsignado, setSoloAsignado] = useState(false);
  const [expandidas, setExpandidas] = useState(() => new Set());

  const grupos = useMemo(() => {
    const porMarca = new Map();
    for (const par of pares) {
      if (!porMarca.has(par.marca)) porMarca.set(par.marca, []);
      porMarca.get(par.marca).push(par);
    }
    return [...porMarca.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([marca, lista]) => [marca, [...lista].sort((a, b) => a.categoria.localeCompare(b.categoria))]);
  }, [pares]);

  const termino = busqueda.trim().toLowerCase();
  const visibles = grupos
    .map(([marca, lista]) => {
      const marcaCoincide = marca.toLowerCase().includes(termino);
      const filtrados = lista.filter((par) => {
        const key = parKey(par.marca, par.categoria);
        if (soloAsignado && !checked.has(key) && !baseline.has(key)) return false;
        return !termino || marcaCoincide || par.categoria.toLowerCase().includes(termino);
      });
      return [marca, filtrados];
    })
    .filter(([, lista]) => lista.length > 0);

  // Searching or filtering opens every remaining marca: the user is looking
  // for rows, hiding them behind one more click defeats the filter.
  const abrirTodo = Boolean(termino) || soloAsignado;
  const todasExpandidas = visibles.length > 0 && visibles.every(([marca]) => expandidas.has(marca));

  const toggleExpandida = (marca) => {
    setExpandidas((prev) => {
      const next = new Set(prev);
      if (next.has(marca)) next.delete(marca);
      else next.add(marca);
      return next;
    });
  };

  const toggleTodas = () => {
    setExpandidas(todasExpandidas ? new Set() : new Set(visibles.map(([marca]) => marca)));
  };

  return (
    <div className={styles.contenedor}>
      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar marca o categoría..."
            aria-label="Buscar marca o categoría"
          />
        </label>
        <label className={styles.toggle}>
          <input type="checkbox" checked={soloAsignado} onChange={(e) => setSoloAsignado(e.target.checked)} />
          Mostrar solo lo asignado
        </label>
        {!abrirTodo && visibles.length > 0 && (
          <button type="button" className="btn-tesla ghost sm" onClick={toggleTodas}>
            {todasExpandidas ? 'Colapsar todo' : 'Expandir todo'}
          </button>
        )}
      </div>

      {visibles.length === 0 ? (
        <div className={styles.vacio}>
          {pares.length === 0
            ? 'No hay pares marca/categoría disponibles todavía.'
            : 'Ninguna marca o categoría coincide con los filtros.'}
        </div>
      ) : (
        <ul className={styles.marcas}>
          {visibles.map(([marca, lista]) => {
            const keys = lista.map((par) => parKey(par.marca, par.categoria));
            const marcados = keys.filter((key) => checked.has(key)).length;
            const todos = marcados === keys.length;
            const parcial = marcados > 0 && !todos;
            const cambios = keys.filter((key) => estadoPar(key, checked, baseline)).length;
            const abierta = abrirTodo || expandidas.has(marca);
            return (
              <li key={marca} className={styles.marca}>
                <div className={styles.marcaHeader}>
                  <input
                    type="checkbox"
                    checked={todos}
                    ref={(el) => {
                      if (el) el.indeterminate = parcial;
                    }}
                    onChange={() => onMarcarPares(lista, !todos)}
                    disabled={disabled}
                    aria-label={`Seleccionar toda la marca ${marca}`}
                  />
                  <button
                    type="button"
                    className={styles.marcaToggle}
                    onClick={() => toggleExpandida(marca)}
                    aria-expanded={abierta}
                    disabled={abrirTodo}
                  >
                    <ChevronRight size={14} className={abierta ? styles.chevronAbierto : styles.chevron} aria-hidden="true" />
                    <span className={styles.marcaNombre}>{marca}</span>
                    <span className={styles.marcaMeta}>
                      {marcados} de {keys.length} {keys.length === 1 ? 'categoría' : 'categorías'}
                    </span>
                  </button>
                  {cambios > 0 && <span className={styles.badgeCambios}>{cambios} sin guardar</span>}
                </div>

                {abierta && (
                  <ul className={styles.categorias}>
                    {lista.map((par) => {
                      const key = parKey(par.marca, par.categoria);
                      const estado = estadoPar(key, checked, baseline);
                      return (
                        <li key={key} className={CLASE_FILA[estado] || styles.fila}>
                          <input
                            type="checkbox"
                            checked={checked.has(key)}
                            onChange={() => onToggle(par.marca, par.categoria)}
                            disabled={disabled}
                            aria-label={`Seleccionar ${par.marca} / ${par.categoria}`}
                          />
                          <span className={estado === 'quita' ? styles.categoriaQuitada : styles.categoria}>{par.categoria}</span>
                          <span className={styles.titular}>
                            <span className={styles.metaLabel}>Titular</span>
                            {par.usuario_id == null ? (
                              <span className={styles.sinTitular}>{SIN_TITULAR}</span>
                            ) : (
                              par.usuario_nombre || `Usuario #${par.usuario_id}`
                            )}
                          </span>
                          {estado === 'agrega' && <span className={styles.badgeAgrega}>Se agrega</span>}
                          {estado === 'quita' && <span className={styles.badgeQuita}>Se quita</span>}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
