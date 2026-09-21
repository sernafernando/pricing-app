import { useEffect, useMemo, useRef } from 'react';
import { marked } from 'marked';
import { loadNovedades } from '../novedades/loadNovedades';
import { sanitizeHtml } from '../utils/sanitizeHtml';
import styles from './Novedades.module.css';

// Prose tags a changelog entry may reasonably need beyond the shared
// sanitizeHtml default allowlist (strong/b/em/i/u/br/p/ul/ol/li/a).
const MARKDOWN_EXTRA_TAGS = ['h1', 'h2', 'h3', 'h4', 'code', 'pre', 'blockquote', 'hr'];

function formatFechaEsAr(date) {
  // Built from the Y/M/D parts (not the ISO string) so there is no
  // timezone off-by-one: `date` is already a local Date built from the
  // filename's Y/M/D, so we format those exact parts.
  const local = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return local.toLocaleDateString('es-AR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

export default function Novedades() {
  const entries = useMemo(() => loadNovedades(), []);
  const scrolledRef = useRef(false);

  useEffect(() => {
    if (scrolledRef.current) return;
    const hash = window.location.hash.replace('#', '');
    if (!hash) return;

    // The referenced article may not be in the DOM yet on the very first
    // paint (entries render synchronously here, but keep this robust to
    // future async loading). Retry briefly via rAF instead of a fixed delay.
    let attempts = 0;
    let rafId;
    const tryScroll = () => {
      const el = document.getElementById(hash);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        scrolledRef.current = true;
        return;
      }
      attempts += 1;
      if (attempts < 20) {
        rafId = requestAnimationFrame(tryScroll);
      }
    };
    tryScroll();

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, [entries]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Novedades</h1>
        <p className={styles.subtitle}>Nuevas funcionalidades y cómo usarlas.</p>
      </div>

      {entries.length === 0 ? (
        <div className={styles.empty}>No hay novedades todavía.</div>
      ) : (
        entries.map((entry) => {
          const html = sanitizeHtml(marked.parse(entry.bodyMarkdown), {
            extraTags: MARKDOWN_EXTRA_TAGS,
          });
          return (
            <article key={entry.slug} id={entry.slug} className={styles.entry}>
              <div className={styles.entryHeader}>
                <h2 className={styles.entryTitle}>{entry.title}</h2>
                <p className={styles.entryDate}>{formatFechaEsAr(entry.date)}</p>
              </div>
              <div className={styles.entryBody} dangerouslySetInnerHTML={{ __html: html }} />
            </article>
          );
        })
      )}
    </div>
  );
}
