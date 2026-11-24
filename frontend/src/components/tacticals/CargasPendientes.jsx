import { useEffect, useState } from 'react';
import { Pagination, StatusPill } from '../kit';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { vigenciaDe } from './tacticalsFormat';
import tablaStyles from './TacticalFila.module.css';
import styles from './TacticalsList.module.css';

/** What each standalone load is, by its `origen` (a tactical line's). */
const TIPO_DE_ORIGEN = {
  sell_in_bono: { texto: 'Bono sell in', tono: 'neutral' },
  sell_in_compra: { texto: 'Compra sell in', tono: 'neutral' },
  sell_out_campana: { texto: 'Campaña sell out', tono: 'info' },
  offset_ganancia: { texto: 'Offset de ganancia', tono: 'info' },
};

/** One page of the inbox; past it, a pager reaches the rest (S11: no pending load may be unreachable). */
const PAGE_SIZE = 50;

/** A legacy profit offset (S10) has no record panel: it is approved right from its row. */
const OFFSET = 'offset_ganancia';

const DIA_MES_ANIO = { day: '2-digit', month: '2-digit', year: 'numeric' };

/** An offset may have no end date. */
const vigencia = (carga) =>
  carga.fecha_hasta
    ? vigenciaDe(carga.fecha_desde, carga.fecha_hasta)
    : `Desde ${formatDateOnly(carga.fecha_desde, DIA_MES_ANIO)}`;

/**
 * The bonuses, purchases and campaigns loaded on their own that wait for approval (tacticals approval S11: "no pending
 * item may be unreachable from the UI"), under the pending tacticals of the "Pendientes de aprobación" filter. `tipo`
 * is the list's Tipo filter (`todos`, `sell_in`, `sell_out`); a new `version` asks again (an approval from a panel).
 * Each row hands its load to `onVer`, which opens its record's panel: a user with `tacticals.aprobar` (`puedeAprobar`)
 * approves it there, after a confirmation. A legacy profit offset (S10) has no panel: its Aprobar hands it to
 * `onAprobarOffset` (the list asks for the confirmation), and without the permission it offers nothing. Nothing shows
 * while none waits.
 */
export default function CargasPendientes({ tipo = 'todos', version = 0, puedeAprobar = false, onVer, onAprobarOffset }) {
  const [respuesta, setRespuesta] = useState(null);
  // The page belongs to its Tipo: another kind starts on the first page.
  const [pagina, setPagina] = useState({ tipo, offset: 0 });
  const offset = pagina.tipo === tipo ? pagina.offset : 0;
  useEffect(() => {
    let activo = true;
    const params = { ...(tipo === 'todos' ? {} : { tipo }), page: offset / PAGE_SIZE + 1, page_size: PAGE_SIZE };
    tacticalsAPI
      .cargasPendientes(params)
      .then(({ data }) => {
        if (!activo) return;
        const total = data.total ?? data.items.length;
        // Approving the last load of the last page empties it: go back to the last page that has loads, so the rest
        // stays reachable (S11) instead of the whole section disappearing.
        if (!data.items.length && offset > 0 && total > 0) {
          setPagina({ tipo, offset: Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE });
          return;
        }
        setRespuesta({ tipo, version, offset, items: data.items, total });
      })
      .catch(() => activo && setRespuesta({ tipo, version, offset, error: true }));
    return () => {
      activo = false;
    };
  }, [tipo, version, offset]);

  // Only the answer to the current query: an older one would list loads of another kind or page.
  const actual = respuesta?.tipo === tipo && respuesta?.version === version && respuesta?.offset === offset ? respuesta : null;
  if (actual?.error) {
    return (
      <div className={styles.aviso} role="alert">
        No se pudieron cargar las cargas sueltas pendientes.
      </div>
    );
  }
  if (!actual?.items?.length) return null;
  const accion = puedeAprobar ? 'Aprobar' : 'Ver';

  return (
    <section className={styles.sueltas} aria-labelledby="cargas-sueltas-titulo">
      <h2 id="cargas-sueltas-titulo" className={styles.sueltasTitulo}>
        Cargas sueltas pendientes de aprobación
      </h2>
      <p className={styles.sueltasNota}>Bonos, compras, campañas y offsets cargados fuera de un tactical. No aplican hasta que los aprueben.</p>
      <div className={styles.lista}>
        <div className={styles.scroller}>
          <table className={tablaStyles.tabla}>
            <thead>
              <tr>
                <th scope="col">Nombre</th>
                <th scope="col">Tipo</th>
                <th scope="col">Marca</th>
                <th scope="col">Vigencia</th>
                <th scope="col">Moneda</th>
                <th scope="col">Cargado por</th>
                <th scope="col">
                  <span className={styles.srOnly}>Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {actual.items.map((carga) => {
                const pill = TIPO_DE_ORIGEN[carga.origen] ?? { texto: carga.origen, tono: 'neutral' };
                const esOffset = carga.origen === OFFSET;
                return (
                  <tr key={`${carga.origen}-${carga.id}`}>
                    <th scope="row" className={styles.sueltaNombre}>
                      {carga.nombre}
                    </th>
                    <td>
                      <StatusPill tone={pill.tono} variant="soft">
                        {pill.texto}
                      </StatusPill>
                    </td>
                    <td>{carga.marca ?? '—'}</td>
                    <td className={styles.sueltaVigencia}>{vigencia(carga)}</td>
                    <td>{carga.moneda}</td>
                    <td>{carga.usuario_nombre ?? '—'}</td>
                    <td className={tablaStyles.num}>
                      {(!esOffset || puedeAprobar) && (
                        <button
                          type="button"
                          className={puedeAprobar ? styles.sueltaAprobar : styles.sueltaVer}
                          aria-label={`${accion} ${carga.nombre}`}
                          onClick={() => (esOffset ? onAprobarOffset?.(carga) : onVer?.(carga))}
                        >
                          {accion}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {actual.total > PAGE_SIZE && (
          <Pagination
            total={actual.total}
            offset={offset}
            pageSize={PAGE_SIZE}
            onOffsetChange={(nuevo) => setPagina({ tipo, offset: nuevo })}
            onPageSizeChange={() => {}}
            pageSizeOptions={[PAGE_SIZE]}
            summary={
              <span>
                mostrando {offset + 1}-{Math.min(offset + PAGE_SIZE, actual.total)} de {actual.total} cargas
              </span>
            }
          />
        )}
      </div>
    </section>
  );
}
