import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { marcasPmAPI } from '../../services/api';
import { ModalAlert } from '../ModalTesla';
import { parKey } from '../parKey';
import lista from './UsuariosLista.module.css';
import styles from './VistaPorMarca.module.css';

function mensajeError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object' && detail.mensaje) return detail.mensaje;
  return fallback;
}

/**
 * VistaPorMarca — "Por marca / par" tab of the Sub-PMs screen.
 *
 * Answers "who manages this marca?": pick a marca, see each category with
 * its titular and sub-PMs, and add one user to several categories at once.
 *
 * Adding goes through the existing atomic bulk PUT for that user, which
 * REPLACES their whole set. The desired set is therefore read fresh from
 * GET /marcas-pm/sub-pms/usuario/{id} right before writing, plus the
 * selected pairs — never from `grantsScope`, which is cosmetic and empty
 * when its read failed or is still in flight (that would silently revoke
 * every other grant). If the fresh read fails, nothing is written.
 *
 * `onCambio(usuarioIds)` tells the parent which users changed so it can
 * reload grants and counts.
 */
export default function VistaPorMarca({ pares, usuarios, grantsScope, onCambio }) {
  const [busqueda, setBusqueda] = useState('');
  const [marca, setMarca] = useState(null);
  const [seleccion, setSeleccion] = useState(() => new Set()); // parKey values
  const [usuarioId, setUsuarioId] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const [alerta, setAlerta] = useState(null); // { tipo, texto }

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

  // Only the ticked pairs of the marca on screen count: when the search
  // swaps the marca, ticks made on another one never leak into a write.
  const seleccionadas = actual ? actual.categorias.filter((par) => seleccion.has(parKey(par.marca, par.categoria))) : [];

  const elegirMarca = (nombre) => {
    setMarca(nombre);
    setSeleccion(new Set());
    setAlerta(null);
  };

  const toggleCategoria = (par) => {
    const key = parKey(par.marca, par.categoria);
    setSeleccion((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const todasSeleccionadas = actual != null && seleccionadas.length === actual.categorias.length;
  const toggleTodas = () => {
    setSeleccion(
      todasSeleccionadas ? new Set() : new Set(actual.categorias.map((par) => parKey(par.marca, par.categoria))),
    );
  };

  const agregar = async () => {
    if (!actual || usuarioId === '' || seleccionadas.length === 0) return;
    const id = Number(usuarioId);
    const nombre = usuarios.find((u) => u.id === id)?.nombre || `usuario #${id}`;
    setOcupado(true);
    setAlerta(null);
    try {
      const { data: actuales } = await marcasPmAPI.obtenerGrantsUsuario(id);
      const deseados = new Map();
      for (const p of actuales?.pares || []) deseados.set(parKey(p.marca, p.categoria), { marca: p.marca, categoria: p.categoria });
      for (const par of seleccionadas) deseados.set(parKey(par.marca, par.categoria), { marca: par.marca, categoria: par.categoria });
      const { data } = await marcasPmAPI.asignarSubPMsBulk(id, [...deseados.values()]);
      const texto =
        data.otorgados === 0
          ? `${nombre} ya era sub-PM de esas categorías de ${actual.nombre}.`
          : `${nombre} agregado como sub-PM en ${data.otorgados} ${data.otorgados === 1 ? 'categoría' : 'categorías'} de ${actual.nombre}.`;
      setAlerta({ tipo: 'success', texto });
      setSeleccion(new Set());
      onCambio([id]);
    } catch (err) {
      console.error('Error al agregar el sub-PM', err);
      setAlerta({ tipo: 'error', texto: `${mensajeError(err, 'Error al agregar el sub-PM')} No se aplicó ningún cambio.` });
    } finally {
      setOcupado(false);
    }
  };

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
                onClick={() => elegirMarca(m.nombre)}
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
            {alerta && <ModalAlert type={alerta.tipo}>{alerta.texto}</ModalAlert>}

            <div className={styles.agregar}>
              <label className={styles.agregarLabel} htmlFor="vistaPorMarcaUsuario">
                Agregar como sub-PM
              </label>
              <select
                id="vistaPorMarcaUsuario"
                className={styles.select}
                value={usuarioId}
                onChange={(e) => setUsuarioId(e.target.value)}
                disabled={ocupado}
              >
                <option value="">Elegí un usuario...</option>
                {usuarios.map((u) => (
                  <option key={u.id} value={u.id}>{u.nombre}</option>
                ))}
              </select>
              <button
                type="button"
                className="btn-tesla outline-subtle-primary sm"
                onClick={agregar}
                disabled={ocupado || usuarioId === '' || seleccionadas.length === 0}
              >
                Agregar a {seleccionadas.length} {seleccionadas.length === 1 ? 'categoría' : 'categorías'}
              </button>
              <button type="button" className="btn-tesla ghost sm" onClick={toggleTodas} disabled={ocupado}>
                {todasSeleccionadas ? 'Deseleccionar todas' : 'Seleccionar todas'}
              </button>
            </div>

            <table className="table-tesla">
              <thead className="table-tesla-head">
                <tr>
                  <th aria-label="Seleccionar" />
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
                      <td>
                        <input
                          type="checkbox"
                          checked={seleccion.has(parKey(par.marca, par.categoria))}
                          onChange={() => toggleCategoria(par)}
                          disabled={ocupado}
                          aria-label={`Seleccionar ${par.categoria}`}
                        />
                      </td>
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
