/**
 * TacticalDatos — the first card of Nuevo tactical, as the approved design draws it: the type (Sell in | Sell out,
 * the ones the user cannot manage off) and the tactical's data: name, brand, the brand's reference, validity,
 * currency, the exchange-rate mode in USD (a fixed rate asks its value), store scope, cap mode preview, conditions
 * and a note.
 *
 * `form` holds the fields as typed; `onChange(cambios)` merges the changed ones; `onTipo(tipo)` switches the type.
 * `gruposTiendas` are clave-collapsed official stores; `ejemploTope` drives the live cap preview.
 */
import Seg from './Seg';
import { ALCANCE_POR_TIENDA, CANALES_TACTICAL, esCanal, previewTope } from './tacticalTiendas';
import styles from './TacticalDatos.module.css';

const TIPOS = [
  { value: 'sell_in', label: 'Sell in' },
  { value: 'sell_out', label: 'Sell out' },
];

const TC_MODOS = [
  { value: 'al_cobro', label: 'Al cobro' },
  { value: 'fijo', label: 'Fijo' },
  { value: 'dia_venta', label: 'Día de la venta' },
];

export default function TacticalDatos({
  form,
  onChange,
  onTipo,
  tiposNoDisponibles = [],
  marcas = [],
  gruposTiendas = [],
  ejemploTope = null,
  alcancePorTienda = ALCANCE_POR_TIENDA,
}) {
  const usd = form.moneda === 'USD';
  const todasTiendas = form.todasTiendas !== false;
  const tiendaKeys = form.tiendaKeys ?? [];
  const topeCompartido = Boolean(form.topeCompartido);
  const preview = previewTope({
    todasTiendas,
    seleccionKeys: tiendaKeys,
    grupos: gruposTiendas,
    topeCompartido,
    ejemploTope,
  });
  const campo = (nombre) => (e) => {
    const { type, checked, value } = e.target;
    onChange({ [nombre]: type === 'checkbox' ? checked : value });
  };
  const toggleKey = (key) => {
    const next = tiendaKeys.includes(key) ? tiendaKeys.filter((k) => k !== key) : [...tiendaKeys, key];
    onChange({ tiendaKeys: next });
  };

  return (
    <section className={styles.card} aria-labelledby="tactical-datos">
      <div className={styles.typebar}>
        <div className={styles.typebarRow}>
          <span className={styles.lbl}>Tipo</span>
          <Seg
            label="Tipo"
            options={TIPOS}
            value={form.tipo}
            disabled={tiposNoDisponibles}
            onChange={onTipo}
          />
        </div>
        <p className={styles.typebarHelp}>
          Sell out: la marca te paga por cada unidad vendida. Sell in: baja el costo de lo que vendés.
        </p>
      </div>
      <div className={styles.cardHead}>
        <h2 id="tactical-datos">Datos del tactical</h2>
      </div>
      <div className={styles.cardBody}>
        <div className={styles.gridForm}>
          <div className={`${styles.field} ${styles.span2}`}>
            <label htmlFor="tactical-nombre">
              Nombre <span className={styles.req} aria-hidden="true">*</span>
            </label>
            <input
              id="tactical-nombre"
              aria-label="Nombre"
              aria-required="true"
              className={styles.ctl}
              type="text"
              maxLength={200}
              value={form.nombre}
              onChange={campo('nombre')}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor="tactical-marca">
              Marca <span className={styles.req} aria-hidden="true">*</span>
            </label>
            <select
              id="tactical-marca"
              aria-label="Marca"
              aria-required="true"
              className={styles.ctl}
              value={form.marca}
              onChange={campo('marca')}
              aria-describedby="tactical-marca-help"
            >
              <option value="">Elegí una marca</option>
              {marcas.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <span className={styles.help} id="tactical-marca-help">
              Se usa para filtrar los tacticals por marca.
            </span>
          </div>
          <div className={styles.field}>
            <label htmlFor="tactical-referencia">
              Referencia de la marca <span className={styles.optional}>(opcional)</span>
            </label>
            <input
              id="tactical-referencia"
              aria-label="Referencia de la marca"
              className={styles.ctl}
              type="text"
              maxLength={200}
              value={form.referencia}
              onChange={campo('referencia')}
            />
          </div>
          <div className={`${styles.field} ${styles.span2}`}>
            <span className={styles.lbl}>
              Vigencia <span className={styles.req} aria-hidden="true">*</span>
            </span>
            <div className={styles.dates}>
              <div className={styles.field}>
                <label htmlFor="tactical-desde" className={styles.subLabel}>
                  Desde
                </label>
                <input
                  id="tactical-desde"
                  aria-required="true"
                  className={styles.ctl}
                  type="date"
                  value={form.fechaDesde}
                  onChange={campo('fechaDesde')}
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="tactical-hasta" className={styles.subLabel}>
                  Hasta
                </label>
                <input
                  id="tactical-hasta"
                  aria-required="true"
                  className={styles.ctl}
                  type="date"
                  value={form.fechaHasta}
                  onChange={campo('fechaHasta')}
                />
              </div>
            </div>
          </div>
          <div className={styles.field}>
            <span className={styles.lbl}>Moneda</span>
            <Seg
              label="Moneda"
              options={[
                { value: 'USD', label: 'USD' },
                { value: 'ARS', label: 'ARS' },
              ]}
              value={form.moneda}
              onChange={(moneda) => onChange({ moneda })}
            />
          </div>
          {usd && (
            <div className={styles.field}>
              <label htmlFor="tactical-tc">Tipo de cambio</label>
              <select id="tactical-tc" className={styles.ctl} value={form.tcModo} onChange={campo('tcModo')}>
                {TC_MODOS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              {form.tcModo === 'fijo' && (
                <input
                  className={`${styles.ctl} ${styles.tcFijo}`}
                  type="text"
                  inputMode="decimal"
                  aria-label="Tipo de cambio fijo"
                  placeholder="ARS por USD"
                  value={form.tipoCambio}
                  onChange={campo('tipoCambio')}
                />
              )}
            </div>
          )}
          <div className={styles.field}>
            <span className={styles.lbl}>Condiciones</span>
            <div className={styles.checks}>
              <label className={styles.check}>
                <input type="checkbox" checked={form.incluyeIva} onChange={campo('incluyeIva')} />
                <span>Los montos incluyen IVA</span>
              </label>
              <label className={styles.check}>
                <input type="checkbox" checked={form.acumulable} onChange={campo('acumulable')} />
                <span>Se acumula con otras campañas</span>
              </label>
            </div>
          </div>
          {alcancePorTienda && (
            <div className={`${styles.field} ${styles.span2}`} data-testid="tactical-tiendas">
              <span className={styles.lbl} id="tactical-tiendas-label">
                Tiendas donde aplica
              </span>
              <div className={styles.checks} role="group" aria-labelledby="tactical-tiendas-label">
                <label className={styles.check}>
                  <input
                    type="checkbox"
                    checked={todasTiendas}
                    onChange={(e) =>
                      onChange({
                        todasTiendas: e.target.checked,
                        tiendaKeys: e.target.checked
                          ? tiendaKeys.filter((k) => CANALES_TACTICAL.some((c) => c.value === k))
                          : tiendaKeys,
                      })
                    }
                  />
                  <span>Todas las tiendas oficiales</span>
                </label>
                {!todasTiendas &&
                  gruposTiendas.map((g) => (
                    <label key={g.value} className={styles.check}>
                      <input
                        type="checkbox"
                        checked={tiendaKeys.includes(g.value)}
                        onChange={() => toggleKey(g.value)}
                      />
                      <span>{g.label}</span>
                    </label>
                  ))}
                {!todasTiendas &&
                  tiendaKeys
                    .filter((k) => !esCanal(k) && !gruposTiendas.some((g) => g.value === k))
                    .map((k) => (
                      // A renewed store no group covers any more: shown so it can be kept or unticked, never dropped.
                      <label key={k} className={styles.check}>
                        <input type="checkbox" checked onChange={() => toggleKey(k)} />
                        <span>{`Tienda ${k}`}</span>
                      </label>
                    ))}
                {CANALES_TACTICAL.map((c) => (
                  <label key={c.value} className={styles.check}>
                    <input
                      type="checkbox"
                      checked={tiendaKeys.includes(c.value)}
                      onChange={() => toggleKey(c.value)}
                    />
                    <span>{c.label}</span>
                  </label>
                ))}
              </div>
              <label className={`${styles.check} ${styles.topeToggle}`}>
                <input type="checkbox" checked={topeCompartido} onChange={campo('topeCompartido')} />
                <span>Tope compartido entre las tiendas elegidas</span>
              </label>
              <div className={styles.previewTope} aria-live="polite">
                <span className={styles.previewTitulo}>Cómo se aplica el tope</span>
                {preview.filas.length === 0 ? (
                  <p className={styles.previewAyuda}>{preview.ayuda}</p>
                ) : (
                  <>
                    <ul className={styles.previewLista}>
                      {preview.filas.map((fila) => (
                        <li key={fila.label}>
                          <span>{fila.label}</span>
                          <span>{fila.valor}</span>
                        </li>
                      ))}
                    </ul>
                    <p className={styles.previewAyuda}>{preview.ayuda}</p>
                  </>
                )}
              </div>
            </div>
          )}
          <div className={`${styles.field} ${styles.span2}`}>
            <label htmlFor="tactical-nota">
              Nota <span className={styles.optional}>(opcional)</span>
            </label>
            <textarea
              id="tactical-nota"
              aria-label="Nota"
              className={styles.ctl}
              placeholder="Condiciones acordadas con la marca, contacto, número de acuerdo…"
              maxLength={2000}
              value={form.nota}
              onChange={campo('nota')}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
