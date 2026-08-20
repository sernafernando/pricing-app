/**
 * PublisherHeader — the sticky header content for the two-pane publisher
 * shell (PR-9, design item a). Rendered as `ModalTesla`'s `title` prop, so
 * it lives in `modal-header-tesla` — already OUTSIDE `modal-body-tesla`'s
 * scroll area, which is what makes it "sticky" for free: no extra CSS
 * position tricks needed, just don't put it inside the scrolling body.
 */
import styles from './TnPublisherShell.module.css';

export default function PublisherHeader({ title, ean, thumbSrc }) {
  return (
    <div className={styles.headerContent}>
      {thumbSrc ? (
        <img src={thumbSrc} alt="" className={styles.headerThumb} />
      ) : (
        <div className={styles.headerThumbPlaceholder} aria-hidden="true" />
      )}
      <div className={styles.headerText}>
        <p className={styles.headerTitle}>{title || 'Publicar producto'}</p>
        {ean && <p className={styles.headerEan}>{ean}</p>}
      </div>
    </div>
  );
}
