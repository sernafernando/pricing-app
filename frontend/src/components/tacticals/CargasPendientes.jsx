import { useEffect, useState } from 'react';
import { StatusPill } from '../kit';
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
  useEffect(() => {
    let activo = true;
    const params = tipo === 'todos' ? {} : { tipo };
    tacticalsAPI
      .cargasPendientes(params)
      .then(({ data }) => activo && setRespuesta({ tipo, version, items: data.items }))
      .catch(() => activo && setRespuesta({ tipo, version, error: true }));
    return () => {
      activo = false;
    };
  }, [tipo, version]);

  // Only the answer to the current query: an older one would list loads of another kind.
  const actual = respuesta?.tipo === tipo && respuesta?.version === version ? respuesta : null;
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
      </div>
    </section>
  );
}
