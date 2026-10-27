import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { parKey } from '../parKey';
import lista from './UsuariosLista.module.css';
import styles from './VistaPorMarca.module.css';

/**
 * VistaPorMarca — "Por marca / par" tab of the Sub-PMs screen.
 *
 * Answers "who manages this marca?": pick a marca, see each category with
 * its titular and sub-PMs. `grantsScope` is every grant in the caller's
 * writable scope (GET /marcas-pm/sub-pms/scope), grouped here per pair.
 */
export default function VistaPorMarca({ pares, grantsScope }) {
  const [busqueda, setBusqueda] = useState('');
  const [marca, setMarca] = useState(null);

  const marcas = useMemo(() => {
    const porMarca = new Map();
    for (const par of pares) {
      if (!porMarca.has(par.marca)) porMarca.set(par.marca, []);
      porMarca.get(par.marca).push(par);
    }
    return [...porMarca.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([nombre, categorias]) => ({
        nombre,
        categorias: [...categorias].sort((a, b) => a.categoria.localeCompare(b.categoria)),
      }));
  }, [pares]);

  const grantsPorPar = useMemo(() => {
    const map = new Map();
    for (const g of grantsScope) {
      const key = parKey(g.marca, g.categoria);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(g);
    }
    return map;
  }, [grantsScope]);

  const termino = busqueda.trim().toLowerCase();
  const marcasVisibles = termino ? marcas.filter((m) => m.nombre.toLowerCase().includes(termino)) : marcas;
  // The detail follows the search: a picked marca that the search hides
  // gives way to the first one still listed.
  const actual = marcasVisibles.find((m) => m.nombre === marca) || marcasVisibles[0] || null;

  return (
    <div className={styles.layout}>
      <aside className={lista.panel} aria-label="Marcas">
        <div className={lista.header}>
          <span className={lista.label}>Marcas</span>
          <label className={lista.search}>
            <Search size={14} aria-hidden="true" />
            <input
              type="search"
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="Buscar marca..."
              aria-label="Buscar marca"
            />
          </label>
        </div>
        <ul className={lista.lista} aria-label="Lista de marcas">
          {marcasVisibles.map((m) => (
            <li key={m.nombre}>
              <button
                type="button"
                className={m.nombre === actual?.nombre ? lista.itemActivo : lista.item}
                aria-pressed={m.nombre === actual?.nombre}
                aria-label={`${m.nombre} (${m.categorias.length})`}
                onClick={() => setMarca(m.nombre)}
              >
                <span className={lista.nombre}>{m.nombre}</span>
                <span className={lista.conteo}>{m.categorias.length}</span>
              </button>
            </li>
          ))}
          {marcasVisibles.length === 0 && <li className={lista.vacio}>Ninguna marca coincide.</li>}
        </ul>
      </aside>

      <section className={styles.detalle}>
        {actual == null ? (
          <p className={lista.vacio}>No hay marcas para mostrar.</p>
        ) : (
          <>
            <h2 className={styles.titulo}>{actual.nombre}</h2>

            <table className="table-tesla">
              <thead className="table-tesla-head">
                <tr>
                  <th>Categoría</th>
                  <th>Titular</th>
                  <th>Sub-PMs</th>
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {actual.categorias.map((par) => {
                  const grants = grantsPorPar.get(parKey(par.marca, par.categoria)) || [];
                  return (
                    <tr key={par.id}>
                      <td>{par.categoria}</td>
                      <td>
                        {par.usuario_id == null ? (
                          <span className={styles.sinTitular}>Sin titular</span>
                        ) : (
                          par.usuario_nombre || `Usuario #${par.usuario_id}`
                        )}
                      </td>
                      <td>
                        {grants.length === 0 ? (
                          <span className={styles.ninguno}>—</span>
                        ) : (
                          <ul className={styles.subpms}>
                            {grants.map((g) => (
                              <li key={g.id} className={styles.chip}>
                                {g.usuario_nombre || `Usuario #${g.usuario_id}`}
                              </li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  );
}
