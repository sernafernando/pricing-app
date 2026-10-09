import { useId } from 'react';
import cellStyles from '../cells.module.css';
import styles from './panel.module.css';

const isBlank = (value) => value === null || value === undefined || value === '';

/** A titled group of a tab. The title names the region, so a reader can jump to it. */
export function Section({ title, children }) {
  const id = useId();
  return (
    <section className={styles.section} aria-labelledby={id}>
      <h3 id={id} className={styles.sectionTitle}>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** The label / value pairs of a section. */
export function Fields({ children }) {
  return <dl className={styles.fields}>{children}</dl>;
}

/** One pair. A value the backend does not have is "—" (S4.1), never 0 or blank. */
export function Field({ label, children }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{isBlank(children) || children === false ? <span className={cellStyles.empty}>—</span> : children}</dd>
    </>
  );
}
