/**
 * MetricTile — Tile para mostrar una métrica numérica con label, valor,
 * hint y un tone visual.
 *
 * 4 tones:
 * - 'debe': border-left rojo, ícono ArrowDownToLine (representa cargo/deuda)
 * - 'haber': border-left verde, ícono ArrowUpFromLine (pago/crédito)
 * - 'neutral': border-left gris, ícono Wallet (saldo neutro)
 * - 'estimate': border-left naranja + striped pattern (valor estimado/parcial)
 *
 * @example
 * <MetricTile label="Saldo ARS" value="$5.000,00" hint="3 movs" tone="debe" />
 * <MetricTile label="Consolidado" value="$10.000,00" tone="estimate" hint="TC del día" />
 */

import { ArrowDownToLine, ArrowUpFromLine, Wallet } from 'lucide-react';
import styles from './MetricTile.module.css';

const DEFAULT_ICONS = {
  debe: ArrowDownToLine,
  haber: ArrowUpFromLine,
  neutral: Wallet,
  estimate: Wallet,
};

const TONE_CLASS = {
  debe: styles.toneDebe,
  haber: styles.toneHaber,
  neutral: styles.toneNeutral,
  estimate: styles.toneEstimate,
};

/**
 * @param {Object} props
 * @param {string} props.label
 * @param {string|number} props.value
 * @param {string} [props.hint]
 * @param {'debe'|'haber'|'neutral'|'estimate'} [props.tone='neutral']
 * @param {React.ReactNode} [props.icon] - override del ícono default por tone
 */
export default function MetricTile({ label, value, hint, tone = 'neutral', icon }) {
  const toneClass = TONE_CLASS[tone] || TONE_CLASS.neutral;
  const DefaultIcon = DEFAULT_ICONS[tone] || Wallet;

  return (
    <div className={`${styles.tile} ${toneClass}`}>
      <div className={styles.labelRow}>
        {icon ?? <DefaultIcon size={12} strokeWidth={2} />}
        <span className={styles.label}>{label}</span>
      </div>
      <div className={styles.value}>{value}</div>
      {hint && <div className={styles.hint}>{hint}</div>}
    </div>
  );
}
