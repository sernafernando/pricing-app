import DateRangeFilter from '../DateRangeFilter';
import SearchInput from '../SearchInput';
import { SegmentedControl } from '../kit';
import { SIN_PROGRAMA } from './sellOutFiltros';
import { VISTAS } from './sellOutProgramas';
import styles from '../../pages/SellIn.module.css';

const TIPOS = [
  { value: 'por_unidad', label: 'Por unidad' },
  { value: 'porcentaje', label: 'Porcentaje' },
  { value: 'monto_total', label: 'Monto total' },
];

function Select({ label, value, onChange, todos = 'Todas', children }) {
  return (
    <label className={styles.selectField}>
      <span className={styles.filterLabel}>{label}</span>
      <select className={styles.select} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{todos}</option>
        {children}
      </select>
    </label>
  );
}

/**
 * The Sell out tab's filter card, laid out like the Sell in one: the period the campaigns' dates overlap, the
 * name search, and estado, tipo, moneda, marca (a product the campaign's groups reach) and grupo. `onChange` gets
 * the changed fields. The Grupo select shows only when there are groups to pick (`grupos`); the Programa select
 * (every program, "Sin programa" or one of `programas`) and the "Ver: Por programa | Lista" switch (`vista`,
 * `onVista`) only when there are programs.
 */
export default function SellOutFiltros({ filtros, onChange, marcas = [], grupos = [], programas = [], vista, onVista }) {
  return (
    <section className={styles.filterCard} aria-label="Filtros de campañas">
      <div className={styles.filterBand}>
        <DateRangeFilter
          fechaDesde={filtros.desde}
          fechaHasta={filtros.hasta}
          filtroActivo={filtros.filtro}
          onChange={({ desde, hasta, filtro }) => onChange({ desde, hasta, filtro })}
        />
        {filtros.desde && (
          <button type="button" className="btn-tesla ghost sm" onClick={() => onChange({ desde: '', hasta: '', filtro: '' })}>
            Todas las fechas
          </button>
        )}
        <div className={styles.searchSlot}>
          <SearchInput value={filtros.q} onChange={(q) => onChange({ q })} debounce={400} placeholder="Buscar campaña por nombre…" />
        </div>
      </div>
      <div className={styles.filterBand}>
        <Select label="Estado" todos="Todos" value={filtros.estado} onChange={(estado) => onChange({ estado })}>
          <option value="activa">Activa</option>
          <option value="anulada">Anulada</option>
        </Select>
        <Select label="Tipo" todos="Todos" value={filtros.tipo} onChange={(tipo) => onChange({ tipo })}>
          {TIPOS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
        <Select label="Moneda" value={filtros.moneda} onChange={(moneda) => onChange({ moneda })}>
          <option value="ARS">ARS</option>
          <option value="USD">USD</option>
        </Select>
        <Select label="Marca" value={filtros.marca} onChange={(marca) => onChange({ marca })}>
          {marcas.map((marca) => (
            <option key={marca} value={marca}>
              {marca}
            </option>
          ))}
        </Select>
        {grupos.length > 0 && (
          <Select label="Grupo" todos="Todos" value={filtros.grupo_id} onChange={(grupo_id) => onChange({ grupo_id })}>
            {grupos.map((g) => (
              <option key={g.id} value={String(g.id)}>
                {g.nombre}
              </option>
            ))}
          </Select>
        )}
        {programas.length > 0 && (
          <Select label="Programa" todos="Todos" value={filtros.programa} onChange={(programa) => onChange({ programa })}>
            <option value={SIN_PROGRAMA}>Sin programa</option>
            {programas.map((p) => (
              <option key={p.id} value={String(p.id)}>
                {p.nombre}
              </option>
            ))}
          </Select>
        )}
        {programas.length > 0 && onVista && (
          <div className={styles.vistaSlot}>
            <span className={styles.filterLabel} aria-hidden="true">
              Ver:
            </span>
            <SegmentedControl label="Ver" options={VISTAS} value={vista} onChange={onVista} />
          </div>
        )}
      </div>
    </section>
  );
}
