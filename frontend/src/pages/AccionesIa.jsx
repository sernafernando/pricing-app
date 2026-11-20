import { useEffect, useState } from 'react';
import { accionesIaAPI } from '../services/api';
import InterruptorEscritura from '../components/accionesIa/InterruptorEscritura';
import ModalDeshacer from '../components/accionesIa/ModalDeshacer';
import AntesDespues from '../components/accionesIa/AntesDespues';
import {
  RESULTADOS,
  etiquetaAccion,
  etiquetaHerramienta,
  etiquetaResultado,
  formatearFecha,
  formatearFechaCompleta,
} from '../components/accionesIa/formato';
import styles from './AccionesIa.module.css';

const LIMITE = 50;
const FILTROS_VACIOS = { usuario_id: '', cliente: '', tool: '', resultado: '', desde: '', hasta: '' };

const puedeDeshacer = (fila) => fila.deshacible && !fila.deshecha && fila.resultado === 'ok';

// Only the filters with a value travel as query params.
const parametros = (filtros, offset) => ({
  limit: LIMITE,
  offset,
  ...Object.fromEntries(Object.entries(filtros).filter(([, valor]) => valor !== '')),
});

// Filter options seen so far (users, clients, tools): the list endpoint is the only source.
function sumarOpciones(previas, items) {
  const usuarios = new Map(previas.usuarios);
  const clientes = new Set(previas.clientes);
  const tools = new Set(previas.tools);
  for (const item of items) {
    if (item.usuario_id != null) usuarios.set(String(item.usuario_id), item.usuario_nombre || `#${item.usuario_id}`);
    if (item.cliente) clientes.add(item.cliente);
    if (item.tool) tools.add(item.tool);
  }
  return { usuarios, clientes, tools };
}

/**
 * "Acciones IA": every write an AI made through MCP (who, which client, what
 * changed, why, result) with Deshacer per row and per plan, plus the switch
 * that allows AI writes at all. Permission mcp.escribir (route + backend).
 */
export default function AccionesIa() {
  const [filtros, setFiltros] = useState(FILTROS_VACIOS);
  const [offset, setOffset] = useState(0);
  const [datos, setDatos] = useState({ total: 0, items: [] });
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const [opciones, setOpciones] = useState({ usuarios: new Map(), clientes: new Set(), tools: new Set() });
  const [deshaciendo, setDeshaciendo] = useState(null);
  const [recarga, setRecarga] = useState(0);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    accionesIaAPI
      .list(parametros(filtros, offset))
      .then(({ data }) => {
        if (!vigente) return;
        const items = Array.isArray(data?.items) ? data.items : [];
        setDatos({ total: data?.total ?? items.length, items });
        setOpciones((previas) => sumarOpciones(previas, items));
      })
      .catch((err) => {
        if (!vigente) return;
        setError(
          err?.response?.status === 403
            ? 'No tenés permiso para ver ni deshacer las acciones de la IA (mcp.escribir).'
            : 'No se pudieron cargar las acciones de la IA.'
        );
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [filtros, offset, recarga]);

  const cambiarFiltro = (campo) => (e) => {
    setFiltros((previos) => ({ ...previos, [campo]: e.target.value }));
    setOffset(0);
  };

  // "Deshacer plan" goes on the first row of each plan that still has something to undo on this page.
  const planesConBoton = new Set();
  const botonPlanEn = new Set();
  for (const fila of datos.items) {
    if (!fila.plan_id || planesConBoton.has(fila.plan_id)) continue;
    if (datos.items.some((f) => f.plan_id === fila.plan_id && puedeDeshacer(f))) {
      planesConBoton.add(fila.plan_id);
      botonPlanEn.add(fila.id);
    }
  }

  const desde = datos.total === 0 ? 0 : offset + 1;
  const hasta = Math.min(offset + datos.items.length, datos.total);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.titulo}>Acciones IA</h1>
        <p className={styles.subtitulo}>
          Cambios que hicieron las IA conectadas (ChatGPT, Claude, Cursor, Gemini CLI). Cada uno se puede deshacer.
        </p>
      </header>

      <InterruptorEscritura />

      <div className={styles.filtros}>
        <label className={styles.filtro}>
          <span>Usuario</span>
          <select value={filtros.usuario_id} onChange={cambiarFiltro('usuario_id')}>
            <option value="">Todos</option>
            {[...opciones.usuarios].map(([id, nombre]) => (
              <option key={id} value={id}>
                {nombre}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filtro}>
          <span>Cliente</span>
          <select value={filtros.cliente} onChange={cambiarFiltro('cliente')}>
            <option value="">Todos</option>
            {[...opciones.clientes].map((cliente) => (
              <option key={cliente} value={cliente}>
                {cliente}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filtro}>
          <span>Herramienta</span>
          <select value={filtros.tool} onChange={cambiarFiltro('tool')}>
            <option value="">Todas</option>
            {[...opciones.tools].map((tool) => (
              <option key={tool} value={tool}>
                {etiquetaHerramienta(tool)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filtro}>
          <span>Resultado</span>
          <select value={filtros.resultado} onChange={cambiarFiltro('resultado')}>
            <option value="">Todos</option>
            {Object.entries(RESULTADOS).map(([valor, etiqueta]) => (
              <option key={valor} value={valor}>
                {etiqueta}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.filtro}>
          <span>Desde</span>
          <input type="date" value={filtros.desde} onChange={cambiarFiltro('desde')} />
        </label>
        <label className={styles.filtro}>
          <span>Hasta</span>
          <input type="date" value={filtros.hasta} onChange={cambiarFiltro('hasta')} />
        </label>
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {!error && (
        <div className="table-container-tesla">
          <table className={`table-tesla striped ${styles.tabla}`}>
            <thead className="table-tesla-head">
              <tr>
                <th>Fecha</th>
                <th>Usuario / cliente</th>
                <th>Acción</th>
                <th>Objetivo</th>
                <th>Antes → después</th>
                <th>Motivo</th>
                <th className={styles.fija}>Resultado</th>
              </tr>
            </thead>
            <tbody className="table-tesla-body">
              {!cargando && datos.items.length === 0 && (
                <tr>
                  <td colSpan={7} className={styles.vacio}>
                    No hay acciones de la IA con estos filtros.
                  </td>
                </tr>
              )}
              {datos.items.map((fila) => (
                <tr key={fila.id}>
                  <td className={styles.nowrap}>
                    <span title={formatearFechaCompleta(fila.created_at)}>{formatearFecha(fila.created_at)}</span>
                  </td>
                  <td>
                    {fila.usuario_nombre}
                    <span className={styles.secundario}>{fila.cliente}</span>
                  </td>
                  <td>
                    {etiquetaAccion(fila.accion)}
                    {fila.undo_of_id && <span className={styles.secundario}>Deshace #{fila.undo_of_id}</span>}
                  </td>
                  <td className={styles.objetivo}>
                    <span className={styles.recortado} title={fila.objetivo_label || fila.objetivo}>
                      {fila.objetivo_label || fila.objetivo}
                    </span>
                  </td>
                  <td>
                    <AntesDespues antes={fila.antes} despues={fila.despues} />
                  </td>
                  <td className={styles.motivo}>
                    <span className={styles.recortado} title={fila.motivo}>
                      {fila.motivo}
                    </span>
                  </td>
                  <td className={styles.fija}>
                    <span className={fila.resultado === 'ok' ? styles.ok : styles.noOk}>
                      {etiquetaResultado(fila.resultado)}
                    </span>
                    {fila.deshecha && <span className={styles.secundario}>Deshecha</span>}
                    {fila.detalle && <span className={styles.secundario}>{fila.detalle}</span>}
                    <div className={styles.botones}>
                      {puedeDeshacer(fila) && (
                        <button
                          type="button"
                          className="btn-tesla outline-subtle-danger sm"
                          onClick={() => setDeshaciendo({ objetivo: { accion_ids: [fila.id] }, titulo: 'Deshacer acción' })}
                        >
                          Deshacer
                        </button>
                      )}
                      {botonPlanEn.has(fila.id) && (
                        <button
                          type="button"
                          className="btn-tesla ghost sm"
                          onClick={() => setDeshaciendo({ objetivo: { plan_id: fila.plan_id }, titulo: 'Deshacer plan' })}
                        >
                          Deshacer plan
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {cargando && <p className={styles.muted}>Cargando...</p>}

      {!error && datos.total > 0 && (
        <div className={styles.paginacion}>
          <span className={styles.muted}>
            {desde}–{hasta} de {datos.total}
          </span>
          <button
            type="button"
            className="btn-tesla ghost sm"
            disabled={cargando || offset === 0}
            onClick={() => setOffset(Math.max(0, offset - LIMITE))}
          >
            Anterior
          </button>
          <button
            type="button"
            className="btn-tesla ghost sm"
            disabled={cargando || offset + LIMITE >= datos.total}
            onClick={() => setOffset(offset + LIMITE)}
          >
            Siguiente
          </button>
        </div>
      )}

      {deshaciendo && (
        <ModalDeshacer
          objetivo={deshaciendo.objetivo}
          titulo={deshaciendo.titulo}
          onClose={() => setDeshaciendo(null)}
          onAplicado={() => setRecarga((n) => n + 1)}
        />
      )}
    </div>
  );
}
