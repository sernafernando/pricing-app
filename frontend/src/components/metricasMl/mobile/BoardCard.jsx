import { useState } from 'react';
import Sparkline from '../Sparkline';
import ListingKindBadge from '../../publicacionesMl/ListingKindBadge';
import { formatSignedMoney, markupTone, moneyTone } from '../../../utils/ventasMlTone';
import {
  ageingTone,
  deltaTone,
  formatAgeing,
  formatDeltaPp,
  formatLastSale,
  formatPct,
  formatUnits,
  publicationDescriptor,
  weeklySums,
} from '../../../utils/metricasMlFormat';
import { LEVEL_LABELS, LEVEL_NOUNS, nodeId } from '../../../utils/metricasMlLevels';
import { formatCompactMoney } from './phoneBoard';
import styles from './BoardCard.module.css';

const WINDOWS = [
  ['units_24h', '24H'],
  ['units_3d', '3D'],
  ['units_7d', '7D'],
  ['units_15d', '15D'],
  ['units_30d', '30D'],
];

const plural = (n, one, many) => `${formatUnits(n)} ${n === 1 ? one : many}`;

/** The second line of a card: SKU · marca · publicaciones for a product, MLA · tipo for a publication, the counts
 * of a node of the "Agrupado" tree. */
function subtitleOf(row, kind) {
  if (kind === 'group') {
    return [
      row.level && (LEVEL_LABELS[row.level] ?? row.level),
      row.products_count != null && plural(row.products_count, 'producto', 'productos'),
      row.publications_count != null && plural(row.publications_count, 'publicación', 'publicaciones'),
    ]
      .filter(Boolean)
      .join(' · ');
  }
  if (kind === 'publication') return [row.mla, publicationDescriptor(row)].filter(Boolean).join(' · ');
  return [row.sku, row.marca, row.publications_count != null && plural(row.publications_count, 'publicación', 'publicaciones')]
    .filter(Boolean)
    .join(' · ');
}

function Figure({ label, children, className = '' }) {
  return (
    <span className={styles.figure}>
      <span className={styles.figureLabel}>{label}</span>
      <span className={`${styles.figureValue} ${className}`}>{children}</span>
    </span>
  );
}

function Pair({ label, children, className = '' }) {
  return (
    <>
      <span className={styles.pairLabel}>{label}</span>
      <span className={`${styles.pairValue} ${className}`}>{children}</span>
    </>
  );
}

const toneClass = (tone) => (tone ? styles[`tone_${tone}`] || '' : '');
// A markup going up reads green, going down red.
const DELTA_TONES = { up: 'good', down: 'negative' };

/** Stock · Ageing · última venta, then the 90-day units trend -- or "Sin stock" when there is none left. */
function Footer({ row, now }) {
  const lastSale = formatLastSale(row.last_sale_at, now);
  const ageing = row.ageing_days == null ? '—' : formatAgeing(row.ageing_days);
  const outOfStock = row.stock === 0;
  const weeks = weeklySums(row.series_units_90d);
  return (
    <span className={styles.footer}>
      <span className={styles.footerText}>
        Stock {formatUnits(row.stock)} · Ageing {ageing} · últ. venta {row.last_sale_at ? lastSale.ago : 'sin ventas'}
      </span>
      {outOfStock ? (
        <span className={styles.outOfStock}>Sin stock</span>
      ) : (
        weeks.some((value) => value) && (
          <Sparkline values={weeks} width={64} height={18} tone={deltaTone(weeks.at(-1) - weeks[0])} label="Unidades por semana, 90 días" />
        )
      )}
    </span>
  );
}

/** What a tap opens: the sales windows, the markup detail, the money and rotation -- the board's columns, stacked. */
function Details({ row, canSeeMargin, tpOn, tpSolo, now }) {
  const sell = canSeeMargin ? row.sell_in_out : null;
  const lastSale = formatLastSale(row.last_sale_at, now);
  return (
    <>
      <span className={styles.sectionTitle}>Ventas (unidades)</span>
      <div className={styles.windows}>
        {WINDOWS.map(([key, label]) => (
          <Figure key={key} label={label}>
            {formatUnits(row[key])}
          </Figure>
        ))}
      </div>
      {canSeeMargin && (
        <>
          <span className={styles.sectionTitle}>Markup</span>
          <div className={styles.pairs}>
            <Pair label="vs anterior" className={toneClass(DELTA_TONES[deltaTone(row.markup_delta_pp)])}>
              {formatDeltaPp(row.markup_delta_pp)}
            </Pair>
            <Pair label="Mín / Máx 90D">
              {row.markup_min_90d == null ? '—' : `${formatPct(row.markup_min_90d)} / ${formatPct(row.markup_max_90d)}`}
            </Pair>
            {sell && sell.total_gauss != null && <Pair label="c/ sell in/out">{formatPct(sell.markup_pct)}</Pair>}
          </div>
        </>
      )}
      <span className={styles.sectionTitle}>Resultado y rotación</span>
      <div className={styles.pairs}>
        {canSeeMargin && !tpSolo && (
          <Pair label="Total Gauss" className={toneClass(moneyTone(row.total_gauss))}>
            {formatSignedMoney(row.total_gauss)}
          </Pair>
        )}
        {canSeeMargin && (tpOn || tpSolo) && (
          <Pair label="Total TP" className={toneClass(moneyTone(row.total_tp))}>
            {formatSignedMoney(row.total_tp)}
          </Pair>
        )}
        {/* The board's cost is the period's total in pesos (the markup's denominator), exactly the desktop Costo
            column -- labelled so it never reads as a unit cost. The board carries no unit cost nor its currency. */}
        {sell && sell.costo != null && (
          <Pair label="Costo del período">
            {formatSignedMoney(sell.costo)}
            {sell.costo_sell_in != null && <span className={styles.small}> c/ sell in {formatSignedMoney(sell.costo_sell_in)}</span>}
          </Pair>
        )}
        <Pair label="Stock · Ageing">
          {formatUnits(row.stock)} · <span className={toneClass(ageingTone(row.ageing_days))}>{formatAgeing(row.ageing_days)}</span>
        </Pair>
        <Pair label="Última venta">{row.last_sale_at ? `${lastSale.ago} · ${lastSale.when}` : 'sin ventas'}</Pair>
      </div>
    </>
  );
}

/** The rows a card opened into (a product's publications, a node's next level), as smaller cards. */
function SubRows({ state, path, ...cardProps }) {
  if (!state || (state.loading && !state.rows?.length)) return <p className={styles.note}>Cargando…</p>;
  if (state.error) return <p className={styles.note}>No se pudieron cargar.</p>;
  const rows = state.rows ?? [];
  if (rows.length === 0) return <p className={styles.note}>Sin filas con estos filtros.</p>;
  return (
    <div className={styles.subRows}>
      {rows.map((sub) => (
        <BoardCard key={sub.key} row={sub} path={[...path, sub.key]} nested {...cardProps} kind={sub.child_level ? 'group' : sub.mla ? 'publication' : 'product'} />
      ))}
    </div>
  );
}

/**
 * One row of the board as a card (design `Main.dc.html`): name, its second line, three figures and the footer;
 * a tap opens the rest of the row's columns. A product opens into its publications and a node of the "Agrupado"
 * tree into its next level, through the page's own `onToggleExpand` -- the same request as the desktop row.
 */
export default function BoardCard({
  row,
  kind,
  path = [row.key],
  nested = false,
  canSeeMargin,
  tpOn,
  tpSolo,
  expanded,
  subRows,
  onToggleExpand,
  now,
}) {
  const [open, setOpen] = useState(false);
  const id = nodeId(path);
  const childrenOpen = expanded.has(id);
  const opensInto =
    kind === 'group' && row.child_level
      ? `Ver ${LEVEL_NOUNS[row.child_level]?.all ?? 'los productos'}`
      : kind === 'product' && !nested && row.publications_count
        ? `Ver sus ${plural(row.publications_count, 'publicación', 'publicaciones')}`
        : null;
  const markup = markupTone(row.markup_pct);
  const cardProps = { canSeeMargin, tpOn, tpSolo, expanded, subRows, onToggleExpand, now };

  return (
    <article className={`${styles.card} ${open ? styles.open : ''} ${nested ? styles.nested : ''}`} aria-label={row.title}>
      <button type="button" className={styles.summary} aria-expanded={open} onClick={() => setOpen((prev) => !prev)}>
        <span className={styles.head}>
          <span className={styles.title}>{row.title}</span>
          <span className={styles.subtitle}>
            {kind === 'publication' && <ListingKindBadge kind={row.listing_kind} />}
            {subtitleOf(row, kind)}
          </span>
        </span>
        <span className={styles.figures}>
          <Figure label="Unid. período" className={styles.num}>
            {formatUnits(row.units)}
          </Figure>
          {canSeeMargin ? (
            <Figure label="Markup" className={toneClass(markup)}>
              {formatPct(row.markup_pct)}
            </Figure>
          ) : (
            <Figure label="30D" className={styles.num}>
              {formatUnits(row.units_30d)}
            </Figure>
          )}
          <Figure label="Facturado" className={styles.num}>
            {formatCompactMoney(row.gross)}
          </Figure>
        </span>
        {!open && <Footer row={row} now={now} />}
      </button>
      {open && (
        <div className={styles.details}>
          <Details row={row} {...cardProps} />
          {opensInto && (
            <button type="button" className={styles.secondary} aria-expanded={childrenOpen} onClick={() => onToggleExpand(row, { path })}>
              {childrenOpen ? 'Ocultar' : opensInto}
            </button>
          )}
          {childrenOpen && <SubRows state={subRows[id]} path={path} {...cardProps} />}
        </div>
      )}
      {open && (
        <button type="button" className={styles.less} onClick={() => setOpen(false)}>
          Menos datos
        </button>
      )}
    </article>
  );
}
