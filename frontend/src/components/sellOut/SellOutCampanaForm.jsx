import { useId } from 'react';
import { SegmentedControl } from '../kit';
import { TC_MODO_LABELS } from './sellOutFormat';
import styles from '../sellIn/SellInPanel.module.css';
import formStyles from './SellOutCampanaForm.module.css';

const TIPOS = [
  { value: 'por_unidad', label: 'Por unidad' },
  { value: 'porcentaje', label: 'Porcentaje' },
];
const MONEDAS = [
  { value: 'USD', label: 'USD' },
  { value: 'ARS', label: 'ARS' },
];

/**
 * The terms of a sell-out campaign (`SellOutCampanaIn`): name, validity, a per-unit amount or a percentage of
 * cost or net price, currency and, in USD, how the exchange rate is taken; caps, VAT, stacking and the product
 * groups it reaches (managed in Gestionar Offsets). Controlled.
 */
export default function SellOutCampanaForm({ valores, onChange, grupos }) {
  const id = useId();
  const set = (patch) => onChange({ ...valores, ...patch });
  const toggleGrupo = (grupoId) =>
    set({
      grupoIds: valores.grupoIds.includes(grupoId)
        ? valores.grupoIds.filter((g) => g !== grupoId)
        : [...valores.grupoIds, grupoId],
    });
  const porUnidad = valores.tipo === 'por_unidad';
  const usd = valores.moneda === 'USD';
  const numero = (key, label, step = '0.01') => (
    <label className={styles.field} htmlFor={`${id}-${key}`}>
      <span className={styles.label}>{label}</span>
      <input
        id={`${id}-${key}`}
        type="number"
        min="0"
        step={step}
        className={styles.input}
        value={valores[key]}
        onChange={(e) => set({ [key]: e.target.value })}
      />
    </label>
  );

  return (
    <>
      <label className={styles.field} htmlFor={`${id}-nombre`}>
        <span className={styles.label}>Nombre</span>
        <input id={`${id}-nombre`} type="text" maxLength={200} className={styles.input} value={valores.nombre} onChange={(e) => set({ nombre: e.target.value })} />
      </label>
      <label className={styles.field} htmlFor={`${id}-desc`}>
        <span className={styles.label}>Descripción</span>
        <input id={`${id}-desc`} type="text" className={styles.input} value={valores.descripcion} onChange={(e) => set({ descripcion: e.target.value })} />
      </label>
      <div className={styles.grid2}>
        <label className={styles.field} htmlFor={`${id}-desde`}>
          <span className={styles.label}>Desde</span>
          <input id={`${id}-desde`} type="date" className={styles.input} value={valores.fechaDesde} onChange={(e) => set({ fechaDesde: e.target.value })} />
        </label>
        <label className={styles.field} htmlFor={`${id}-hasta`}>
          <span className={styles.label}>Hasta</span>
          <input id={`${id}-hasta`} type="date" className={styles.input} value={valores.fechaHasta} onChange={(e) => set({ fechaHasta: e.target.value })} />
        </label>
      </div>
      <div className={styles.grid2}>
        <div className={styles.field}>
          <span className={styles.label}>Tipo</span>
          <SegmentedControl label="Tipo" options={TIPOS} value={valores.tipo} onChange={(tipo) => set({ tipo })} />
        </div>
        <div className={styles.field}>
          <span className={styles.label}>Moneda</span>
          <SegmentedControl label="Moneda" options={MONEDAS} value={valores.moneda} onChange={(moneda) => set({ moneda })} />
        </div>
      </div>
      {porUnidad ? (
        numero('montoUnit', 'Monto por unidad')
      ) : (
        <div className={styles.grid2}>
          {numero('porcentaje', 'Porcentaje', '0.0001')}
          <label className={styles.field} htmlFor={`${id}-base`}>
            <span className={styles.label}>Base del porcentaje</span>
            <select id={`${id}-base`} className={styles.select} value={valores.basePorcentaje} onChange={(e) => set({ basePorcentaje: e.target.value })}>
              <option value="costo">Costo</option>
              <option value="precio_neto">Precio neto</option>
            </select>
          </label>
        </div>
      )}
      {usd && (
        <div className={styles.grid2}>
          <label className={styles.field} htmlFor={`${id}-tc`}>
            <span className={styles.label}>Tipo de cambio</span>
            <select id={`${id}-tc`} className={styles.select} value={valores.tcModo} onChange={(e) => set({ tcModo: e.target.value })}>
              {Object.entries(TC_MODO_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {valores.tcModo === 'fijo' && numero('tipoCambio', 'Tipo de cambio fijo', '0.000001')}
        </div>
      )}
      <div className={styles.grid2}>
        {numero('topeUnidades', 'Tope de unidades', '1')}
        {numero('topeMonto', `Tope de monto (${valores.moneda})`)}
      </div>
      <label className={formStyles.check}>
        <input type="checkbox" checked={valores.montoIncluyeIva} onChange={(e) => set({ montoIncluyeIva: e.target.checked })} />
        El monto incluye IVA
      </label>
      <label className={formStyles.check}>
        <input type="checkbox" checked={valores.acumulable} onChange={(e) => set({ acumulable: e.target.checked })} />
        Acumulable con otras campañas
      </label>
      <fieldset className={formStyles.grupos}>
        <legend className={styles.label}>Productos alcanzados</legend>
        {grupos.length === 0 && <p className={styles.hint}>No hay grupos. Se crean en Gestionar Offsets.</p>}
        {grupos.map((grupo) => (
          <label key={grupo.id} className={formStyles.check}>
            <input type="checkbox" checked={valores.grupoIds.includes(grupo.id)} onChange={() => toggleGrupo(grupo.id)} />
            {grupo.nombre}
          </label>
        ))}
      </fieldset>
    </>
  );
}
