import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Plus, RefreshCw } from 'lucide-react';
import { SegmentedControl, StatusPill } from '../kit';
import { sellOutAPI, sellOutProgramasAPI } from '../../services/sellOutAPI';
import { apiMessage } from '../sellIn/sellInFormat';
import SellOutAsignarPrograma from './SellOutAsignarPrograma';
import SellOutProgramaDialog from './SellOutProgramaDialog';
import SellOutRenovarPrograma from './SellOutRenovarPrograma';
import { fechasDe, nombreNormalizado, plural } from './sellOutProgramas';
import tableStyles from '../sellIn/SellInTable.module.css';
import styles from './SellOutProgramas.module.css';

/** Campaigns asked per expanded program: the list endpoint's maximum (`page_size` le=200). */
const CAMPANAS_POR_PROGRAMA = 200;
const COLUMNAS = 7;

export const JERARQUIA =
  'Programa es el nivel superior: agrupa una campaña y sus repeticiones a lo largo de los quarters. ' +
  'Cada campaña es el monto de un período sobre un alcance; Renovar crea la del quarter siguiente en el mismo programa.';

const ESTADOS = [
  { value: 'activo', label: 'Activos' },
  { value: 'archivado', label: 'Archivados' },
  { value: '', label: 'Todos' },
];

/** A program's campaigns (`GET /sell-out/campanas?programa_id=`), read when it is expanded; with `puedeGestionar`
 * they can be taken out of it (`POST /asignar` with `programa_id: null`) or moved to another program. */
function CampanasDelPrograma({ programa, programas, puedeGestionar, onCambio, onAviso }) {
  const [lista, setLista] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const [seleccion, setSeleccion] = useState(() => new Set());
  const [moviendo, setMoviendo] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let activo = true;
    setError(null);
    sellOutAPI
      .listar({ programa_id: programa.id, page: 1, page_size: CAMPANAS_POR_PROGRAMA })
      .then(({ data }) => activo && setLista(data))
      .catch(() => activo && setError('No se pudieron cargar las campañas del programa.'));
    return () => {
      activo = false;
    };
  }, [programa.id, version]);

  const alternar = (campanaId) =>
    setSeleccion((actual) => {
      const siguiente = new Set(actual);
      if (siguiente.has(campanaId)) siguiente.delete(campanaId);
      else siguiente.add(campanaId);
      return siguiente;
    });
  const recargar = () => {
    setSeleccion(new Set());
    setVersion((v) => v + 1);
    onCambio();
  };
  const quitar = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellOutProgramasAPI.asignar([...seleccion], null);
      onAviso(`${plural(data.asignadas, 'campaña quitada', 'campañas quitadas')} de «${programa.nombre}».`);
      recargar();
    } catch (err) {
      setError(apiMessage(err, 'No se pudieron quitar las campañas del programa.'));
    } finally {
      setBusy(false);
    }
  };

  if (!lista && !error) return <p className={styles.aviso}>Cargando campañas…</p>;
  return (
    <div className={styles.campanas}>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {puedeGestionar && seleccion.size > 0 && (
        <div className={styles.barra}>
          <span>{plural(seleccion.size, 'seleccionada', 'seleccionadas')}</span>
          <button type="button" className="btn-tesla outline sm" onClick={quitar} disabled={busy}>
            Quitar del programa
          </button>
          <button type="button" className="btn-tesla outline sm" onClick={() => setMoviendo(true)} disabled={busy}>
            Mover a otro programa
          </button>
        </div>
      )}
      {lista && (
        <table className={tableStyles.table}>
          <thead>
            <tr>
              {puedeGestionar && <th aria-label="Seleccionar" />}
              <th>Campaña</th>
              <th>Vigencia</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {lista.items.length === 0 && (
              <tr>
                <td colSpan={puedeGestionar ? 4 : 3} className={tableStyles.empty}>
                  Este programa todavía no tiene campañas.
                </td>
              </tr>
            )}
            {lista.items.map((c) => (
              <tr key={c.id}>
                {puedeGestionar && (
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Seleccionar ${c.nombre}`}
                      checked={seleccion.has(c.id)}
                      onChange={() => alternar(c.id)}
                    />
                  </td>
                )}
                <td>{c.nombre}</td>
                <td>{fechasDe(c.fecha_desde, c.fecha_hasta)}</td>
                <td>
                  <StatusPill tone={c.estado === 'activa' ? 'success' : 'danger'}>
                    {c.estado === 'activa' ? 'Activa' : 'Anulada'}
                  </StatusPill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {lista && lista.total > lista.items.length && (
        <p className={styles.pie}>{`Se muestran ${lista.items.length} de ${lista.total} campañas.`}</p>
      )}
      {moviendo && (
        <SellOutAsignarPrograma
          campanaIds={[...seleccion]}
          programas={programas.filter((p) => p.id !== programa.id)}
          onClose={() => setMoviendo(false)}
          onProgramaCreado={onCambio}
          onAsignadas={(texto) => {
            setMoviendo(false);
            onAviso(texto);
            recargar();
          }}
        />
      )}
    </div>
  );
}

function FilaPrograma({ programa, abierto, onAlternar, puedeGestionar, onEditar, onEstado, onRenovar, busy }) {
  const Chevron = abierto ? ChevronDown : ChevronRight;
  const archivado = programa.estado === 'archivado';
  return (
    <tr className={abierto ? tableStyles.rowSelected : ''}>
      <td>
        <div className={styles.nombre}>
          <button
            type="button"
            className={styles.alternar}
            aria-expanded={abierto}
            aria-label={`Ver campañas de ${programa.nombre}`}
            onClick={onAlternar}
          >
            <Chevron size={16} aria-hidden="true" />
          </button>
          <div>
            <div className={styles.titulo}>{programa.nombre}</div>
            {programa.descripcion && <div className={tableStyles.sub}>{programa.descripcion}</div>}
          </div>
        </div>
      </td>
      <td className={tableStyles.num}>{programa.campanas}</td>
      <td className={tableStyles.num}>{programa.activas}</td>
      <td className={tableStyles.num}>{programa.nombres}</td>
      <td>{programa.desde ? fechasDe(programa.desde, programa.hasta) : 'Sin campañas'}</td>
      <td>
        <StatusPill tone={archivado ? 'neutral' : 'success'}>{archivado ? 'Archivado' : 'Activo'}</StatusPill>
      </td>
      <td>
        {puedeGestionar && (
          <div className={styles.acciones}>
            {!archivado && (
              <button type="button" className="btn-tesla ghost sm" onClick={onRenovar} disabled={busy}>
                <RefreshCw size={14} aria-hidden="true" /> Renovar programa
              </button>
            )}
            <button type="button" className="btn-tesla ghost sm" onClick={onEditar} disabled={busy}>
              Editar
            </button>
            <button
              type="button"
              className="btn-tesla ghost sm"
              onClick={() => onEstado(archivado ? 'activo' : 'archivado')}
              disabled={busy}
            >
              {archivado ? 'Reactivar' : 'Archivar'}
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

/**
 * The Programas view of the Sell out tab (campanas-sistema slice E; Stitch 5ee03d7d plus the management the owner
 * asked for): the programs (`programas`, every one from `useProgramas`) with their campaigns' counts and dates, filtered
 * by state and name here. With `puedeGestionar` (`sell_out.gestionar`): "Nuevo programa", "Editar", "Archivar" /
 * "Reactivar" (`PATCH estado`), "Renovar programa" on active programs (`SellOutRenovarPrograma`), and in an expanded program "Quitar del programa" / "Mover a otro programa".
 * `onCambio()` runs after any change so the page reads programs and campaigns again.
 */
export default function SellOutProgramas({ programas, puedeGestionar = false, onCambio }) {
  const [estado, setEstado] = useState('activo');
  const [q, setQ] = useState('');
  const [abierto, setAbierto] = useState(null);
  const [dialogo, setDialogo] = useState(null); // { programa } to edit, {} to create
  const [renovando, setRenovando] = useState(null); // the program "Renovar programa" opened for
  const [aviso, setAviso] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const buscado = nombreNormalizado(q);
  const visibles = programas.filter(
    (p) => (estado === '' || p.estado === estado) && nombreNormalizado(p.nombre).includes(buscado),
  );

  const cambiarEstado = async (programa, nuevo) => {
    setBusy(true);
    setError(null);
    try {
      await sellOutProgramasAPI.editar(programa.id, { estado: nuevo });
      setAviso(`Programa «${programa.nombre}» ${nuevo === 'archivado' ? 'archivado' : 'reactivado'}.`);
      onCambio();
    } catch (err) {
      setError(apiMessage(err, 'No se pudo cambiar el estado del programa.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={styles.programas} aria-labelledby="sell-out-programas-titulo">
      <div className={styles.cabecera}>
        <div>
          <h2 id="sell-out-programas-titulo" className={styles.encabezado}>
            Programas
          </h2>
          <p className={styles.jerarquia}>{JERARQUIA}</p>
        </div>
        {puedeGestionar && (
          <button type="button" className="btn-tesla primary sm" onClick={() => setDialogo({})}>
            <Plus size={14} aria-hidden="true" /> Nuevo programa
          </button>
        )}
      </div>
      <div className={styles.filtros}>
        <input
          type="search"
          className={styles.buscar}
          aria-label="Buscar programa"
          placeholder="Buscar programa"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <SegmentedControl label="Estado del programa" options={ESTADOS} value={estado} onChange={setEstado} />
      </div>
      {aviso && (
        <p className={styles.ok} role="status">
          {aviso}
        </p>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={tableStyles.scroller}>
        <table className={tableStyles.table}>
          <thead>
            <tr>
              <th>Programa</th>
              <th className={tableStyles.num}>Campañas</th>
              <th className={tableStyles.num}>Activas</th>
              <th className={tableStyles.num}>Nombres distintos</th>
              <th>Vigencia</th>
              <th>Estado</th>
              <th aria-label="Acciones" />
            </tr>
          </thead>
          {visibles.length === 0 && (
            <tbody>
              <tr>
                <td colSpan={COLUMNAS} className={tableStyles.empty}>
                  No hay programas con esos filtros.
                </td>
              </tr>
            </tbody>
          )}
          {visibles.map((p) => (
            <tbody key={p.id}>
              <FilaPrograma
                programa={p}
                abierto={abierto === p.id}
                onAlternar={() => setAbierto((actual) => (actual === p.id ? null : p.id))}
                puedeGestionar={puedeGestionar}
                onEditar={() => setDialogo({ programa: p })}
                onEstado={(nuevo) => cambiarEstado(p, nuevo)}
                onRenovar={() => setRenovando(p)}
                busy={busy}
              />
              {abierto === p.id && (
                <tr>
                  <td colSpan={COLUMNAS} className={styles.anidada}>
                    <CampanasDelPrograma
                      programa={p}
                      programas={programas}
                      puedeGestionar={puedeGestionar}
                      onCambio={onCambio}
                      onAviso={setAviso}
                    />
                  </td>
                </tr>
              )}
            </tbody>
          ))}
        </table>
      </div>
      {renovando && (
        <SellOutRenovarPrograma
          programa={renovando}
          onClose={() => setRenovando(null)}
          onRenovado={(texto) => {
            setRenovando(null);
            setAviso(texto);
            onCambio();
          }}
        />
      )}
      {dialogo && (
        <SellOutProgramaDialog
          programa={dialogo.programa}
          onClose={() => setDialogo(null)}
          onGuardado={(guardado) => {
            setDialogo(null);
            setAviso(`Programa «${guardado.nombre}» ${dialogo.programa ? 'guardado' : 'creado'}.`);
            onCambio();
          }}
        />
      )}
    </section>
  );
}
