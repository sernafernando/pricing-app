import { useId } from 'react';
import cellStyles from '../cells.module.css';
import { isBlank } from './format';
import styles from './resumen.module.css';

/*
 * The building blocks of the Resumen tabs (S5): a titled block, a card, a group of label / value lines, chips. Each
 * block is a region named by its title, so a reader (and a test) can jump to it.
 */

/** A titled block of the tab; `aside` sits at the right of the title (a caption, an action). */
export function Block({ title, aside, children }) {
  const id = useId();
  return (
    <section className={styles.block} aria-labelledby={id}>
      <div className={styles.blockHead}>
        <h3 id={id} className={styles.blockTitle}>
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A bordered card with its own small title; `badge` sits at the right of the title. */
export function Card({ title, badge, children }) {
  const id = useId();
  return (
    <section className={styles.card} aria-labelledby={id}>
      <div className={styles.cardHead}>
        <h3 id={id} className={styles.cardTitle}>
          {title}
        </h3>
        {badge}
      </div>
      {children}
    </section>
  );
}

/** A group of lines under a small caps title. */
export function Group({ title, children }) {
  return (
    <div className={styles.group}>
      <h4 className={styles.groupTitle}>{title}</h4>
      <dl className={styles.lines}>{children}</dl>
    </div>
  );
}

/**
 * One label / value line. A value the backend does not have is "—" (S4.1); with `hideEmpty` the line is left out
 * instead (the ML data, where most fields are often empty).
 */
export function Line({ label, children, hideEmpty = false }) {
  const blank = isBlank(children);
  if (blank && hideEmpty) return null;
  return (
    <div className={styles.line}>
      <dt>{label}</dt>
      <dd>{blank ? <span className={cellStyles.empty}>—</span> : children}</dd>
    </div>
  );
}

/** A small pill; `tone` is success, warning, danger or neutral (the default). */
export function Chip({ tone, children, title }) {
  return (
    <span className={styles.chip} data-tone={tone} title={title}>
      {children}
    </span>
  );
}

/** A row of chips after a quiet label; `null` when there is nothing to list. */
export function ChipRow({ label, items, emptyDash = false }) {
  const list = Array.isArray(items) ? items.filter((item) => !isBlank(item)) : [];
  if (list.length === 0 && !emptyDash) return null;
  return (
    <div className={styles.chips} role="group" aria-label={label}>
      <span className={styles.chipsLabel}>{label}</span>
      {list.length === 0 ? (
        <span className={cellStyles.empty}>—</span>
      ) : (
        list.map((item, index) => <Chip key={`${item}-${index}`}>{item}</Chip>)
      )}
    </div>
  );
}
