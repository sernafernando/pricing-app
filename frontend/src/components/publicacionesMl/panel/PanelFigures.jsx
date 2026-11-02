import cellStyles from '../cells.module.css';
import styles from './panel.module.css';

/**
 * The few figures a panel keeps in its header on every tab (S1): label, value
 * and an optional note under it. A figure without a value shows "—", never 0;
 * a figure the viewer may not see is simply not in `figures`. With `hideLabel`
 * the label is only for screen readers (the value says what it is).
 *
 * @param {object} props
 * @param {string} props.label Accessible name of the strip.
 * @param {string} [props.caption] A line under the figures saying what they are measured over.
 * @param {{ key: string, label: string, hideLabel?: boolean, value: import('react').ReactNode, note?: import('react').ReactNode }[]} props.figures
 */
export default function PanelFigures({ label, caption, figures }) {
  if (figures.length === 0) return null;
  return (
    <section className={styles.figures} aria-label={label}>
      <dl className={styles.figureList}>
        {figures.map((figure) => (
          <div key={figure.key} className={styles.figure}>
            <dt className={figure.hideLabel ? styles.visuallyHidden : styles.figureLabel}>{figure.label}</dt>
            <dd className={styles.figureValue}>
              {figure.value == null ? <span className={cellStyles.empty}>—</span> : figure.value}
              {figure.note && <span className={styles.figureNote}>{figure.note}</span>}
            </dd>
          </div>
        ))}
      </dl>
      {caption && <p className={styles.figureNote}>{caption}</p>}
    </section>
  );
}
