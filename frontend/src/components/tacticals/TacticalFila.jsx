import { ChevronDown, ChevronRight, Wallet } from 'lucide-react';
import { StatusPill } from '../kit';
import {
  COLUMNAS_TACTICAL,
  alcanceDe,
  avanceDeLinea,
  avanceDeTactical,
  estadoDe,
  formatMontoTactical,
  formatUnidades,
  vacio,
  valorDeLinea,
  vigenciaDe,
} from './tacticalsFormat';
import TacticalAcciones from './TacticalAcciones';
import TacticalCobranza from './TacticalCobranza';
import { estadoDeCobranza } from './tacticalCobranza';
import styles from './TacticalFila.module.css';

const TIPO_PILL = { sell_in: { texto: 'Sell in', tono: 'neutral' }, sell_out: { texto: 'Sell out', tono: 'info' } };
const PORCENTAJE = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });
/** An invoice total still waiting for its invoice: no purchase yet, so no sales to open. */
const SIN_VENTAS = 'sell_in_factura_pendiente';
const GUION = <span className={styles.guion}>—</span>;

function Barra({ avance, etiqueta }) {
  return (
    <div className={`${styles.bar} ${styles[avance.tono] ?? ''}`} role="img" aria-label={`${PORCENTAJE.format(avance.porcentaje)}% ${etiqueta}`}>
      <span style={{ width: `${avance.porcentaje}%` }} />
    </div>
  );
}

/** "Qué incluye": product chips, or the brand / category / invoice the line reaches. */
function QueIncluye({ linea }) {
  if (linea.alcance === 'productos') {
    return (
      <span className={styles.chips}>
        {(linea.productos ?? []).map((p) => (
          <span key={p.item_id} className={styles.chip} title={p.descripcion}>
            {p.descripcion}
          </span>
        ))}
      </span>
    );
  }
  const { titulo, detalle } = alcanceDe(linea);
  return (
    <span className={styles.alcance}>
      {titulo}
      {detalle && <small>{detalle}</small>}
    </span>
  );
}

/** The loaded order: by `linea` (the POSTed line; a per-product line's children share it), then by child id. */
const enOrden = (lineas) => [...lineas].sort((x, y) => (x.linea ?? 0) - (y.linea ?? 0) || x.id - y.id);

function Lineas({ tactical, onVerLinea }) {
  const lineas = enOrden(tactical.lineas);
  return (
    <div className={styles.sub}>
      <p className={styles.subTitulo}>Líneas del tactical ({lineas.length})</p>
      <table className={styles.subTabla}>
        <thead>
          <tr>
            <th scope="col">Qué incluye</th>
            <th scope="col" className={styles.num}>Monto</th>
            <th scope="col" className={styles.num}>Tope unidades</th>
            <th scope="col" className={styles.num}>Usadas</th>
            <th scope="col" className={styles.num}>Tope monto</th>
            <th scope="col" className={styles.num}>Usado</th>
            <th scope="col">Avance</th>
            {onVerLinea && <th scope="col">Ventas</th>}
          </tr>
        </thead>
        <tbody>
          {lineas.map((linea, i) => {
            const avance = avanceDeLinea(linea);
            return (
              <tr key={linea.id}>
                <td>
                  <QueIncluye linea={linea} />
                </td>
                <td className={styles.num}>{valorDeLinea(linea, tactical.tipo_cambio)}</td>
                <td className={styles.num}>{vacio(linea.tope_unidades) ? GUION : formatUnidades(linea.tope_unidades)}</td>
                <td className={styles.num}>{vacio(linea.unidades_usadas) ? GUION : formatUnidades(linea.unidades_usadas)}</td>
                <td className={styles.num}>{vacio(linea.tope_monto) ? GUION : formatMontoTactical(linea.tope_monto, linea.moneda)}</td>
                <td className={styles.num}>{formatMontoTactical(linea.monto_usado, linea.moneda)}</td>
                <td>
                  {avance ? (
                    <div className={styles.subAvance}>
                      <Barra avance={avance} etiqueta={vacio(linea.tope_unidades) ? 'del tope de monto' : 'del tope de unidades'} />
                      {avance.tono === 'full' && <span className={styles.tag}>Tope alcanzado</span>}
                    </div>
                  ) : (
                    GUION
                  )}
                </td>
                {onVerLinea && (
                  <td>
                    {linea.origen === SIN_VENTAS ? (
                      GUION
                    ) : (
                      <button
                        type="button"
                        className={styles.verVentas}
                        aria-label={`Ver ventas de la línea ${i + 1}`}
                        onClick={() => onVerLinea(linea)}
                      >
                        Ver ventas
                      </button>
                    )}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One tactical as a `<tbody>`: its row (type, brand, dates, line count, progress over the caps, state) and, when
 * `abierto`, its lines with amount, caps, usage and a "Tope alcanzado" mark. `acciones` (`{ label, onSelect }`) fill
 * the row's actions menu; none, no menu. With `onVerLinea`, each line has "Ver ventas", which hands that line (its
 * child record: `origen` and `id`) over; an invoice total still waiting for its invoice has none (no sales yet). Its
 * Cobranza cell says Pendiente or Cobrado with the date; with
 * `cobranza.puede` (the user manages its kind) it has Cargar / Editar cobro, which toggles the Cobranza box under the
 * row (`cobranza.abierta`, `cobranza.onAlternar`; `cobranza.onGuardado` after a save or an undo).
 */
/** Every brand of the tactical (S3); a tactical read before S3 has only `marca`. */
const marcasDe = (tactical) =>
  (tactical.marcas?.length ? tactical.marcas : [tactical.marca]).filter((m) => !vacio(m)).join(', ');

export default function TacticalFila({ tactical, abierto, onAlternar, acciones = [], onVerLinea, cobranza = {} }) {
  const cobro = estadoDeCobranza(tactical);
  const accionCobro = tactical.cobranza ? 'Editar cobro' : 'Cargar cobro';
  const tipo = TIPO_PILL[tactical.tipo] ?? { texto: tactical.tipo, tono: 'neutral' };
  const estado = estadoDe(tactical);
  const { unidades, monto } = avanceDeTactical(tactical.lineas);
  const Chevron = abierto ? ChevronDown : ChevronRight;
  return (
    <tbody>
      <tr className={abierto ? styles.abierto : undefined}>
        <td className={styles.twisty}>
          <button
            type="button"
            className={styles.alternar}
            aria-expanded={abierto}
            aria-controls={abierto ? `tactical-${tactical.id}-lineas` : undefined}
            aria-label={`${abierto ? 'Ocultar' : 'Ver'} las líneas de ${tactical.nombre}`}
            onClick={onAlternar}
          >
            <Chevron size={16} aria-hidden="true" />
          </button>
        </td>
        <td>
          <span className={styles.nombre}>{tactical.nombre}</span>
          {tactical.referencia && <small className={styles.referencia}>{tactical.referencia}</small>}
        </td>
        <td>
          <StatusPill tone={tipo.tono} variant="soft">
            {tipo.texto}
          </StatusPill>
        </td>
        <td>{marcasDe(tactical) || GUION}</td>
        <td className={styles.nowrap}>{vigenciaDe(tactical.fecha_desde, tactical.fecha_hasta, tactical.por_factura)}</td>
        <td className={styles.num}>{tactical.lineas.length}</td>
        <td>
          <div className={styles.avance}>
            {unidades ? (
              <>
                <Barra avance={unidades} etiqueta="de las unidades consumidas" />
                <span className={styles.unidades}>
                  {formatUnidades(unidades.usadas)} / {formatUnidades(unidades.tope)} u
                </span>
              </>
            ) : (
              GUION
            )}
            <span className={styles.monto}>{monto}</span>
          </div>
        </td>
        <td>
          <StatusPill tone={estado.tono} variant="soft">
            {estado.texto}
          </StatusPill>
        </td>
        <td>
          <div className={styles.cobranza}>
            <StatusPill tone={cobro.tono} variant="soft">
              {cobro.texto}
            </StatusPill>
            {cobranza.puede && (
              <button
                type="button"
                className={`btn-tesla outline-subtle-success sm ${styles.cobro}`}
                aria-expanded={Boolean(cobranza.abierta)}
                aria-controls={cobranza.abierta ? `tactical-${tactical.id}-cobranza-fila` : undefined}
                aria-label={`${accionCobro} de ${tactical.nombre}`}
                onClick={cobranza.onAlternar}
              >
                <Wallet size={14} aria-hidden="true" />
                {accionCobro}
              </button>
            )}
          </div>
        </td>
        <td>{acciones.length > 0 && <TacticalAcciones nombre={tactical.nombre} acciones={acciones} />}</td>
      </tr>
      {cobranza.abierta && (
        <tr id={`tactical-${tactical.id}-cobranza-fila`} className={styles.filaLineas}>
          <td colSpan={COLUMNAS_TACTICAL}>
            <TacticalCobranza tactical={tactical} onGuardado={cobranza.onGuardado} onCerrar={cobranza.onAlternar} />
          </td>
        </tr>
      )}
      {abierto && (
        <tr id={`tactical-${tactical.id}-lineas`} className={styles.filaLineas}>
          <td colSpan={COLUMNAS_TACTICAL}>
            <Lineas tactical={tactical} onVerLinea={onVerLinea} />
          </td>
        </tr>
      )}
    </tbody>
  );
}
