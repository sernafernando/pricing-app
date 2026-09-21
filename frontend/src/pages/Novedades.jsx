import { useEffect, useMemo, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import { marked } from 'marked';
import { loadNovedades } from '../novedades/loadNovedades';
import { sanitizeHtml } from '../utils/sanitizeHtml';
import styles from './Novedades.module.css';

// Prose tags a changelog entry may reasonably need beyond the shared
// sanitizeHtml default allowlist (strong/b/em/i/u/br/p/ul/ol/li/a).
const MARKDOWN_EXTRA_TAGS = ['h1', 'h2', 'h3', 'h4', 'code', 'pre', 'blockquote', 'hr'];

const MESES_CORTOS = [
  'ENE',
  'FEB',
  'MAR',
  'ABR',
  'MAY',
  'JUN',
  'JUL',
  'AGO',
  'SEP',
  'OCT',
  'NOV',
  'DIC',
];

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

function formatMesCorto(date) {
  return `${MESES_CORTOS[date.getMonth()]} ${date.getFullYear()}`;
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
        <p className={styles.eyebrow}>
          <Sparkles size={14} aria-hidden="true" />
          Qué hay de nuevo
        </p>
        <h1 className={styles.title}>Novedades</h1>
        <p className={styles.subtitle}>
          Las funciones nuevas de Pricing y cómo se usan. La más reciente arriba.
        </p>
      </div>

      {entries.length === 0 ? (
        <div className={styles.empty}>No hay novedades todavía.</div>
      ) : (
        <div className={styles.timeline}>
          {entries.map((entry, index) => {
            const isNewest = index === 0;
            const html = sanitizeHtml(marked.parse(entry.bodyMarkdown), {
              extraTags: MARKDOWN_EXTRA_TAGS,
            });
            return (
              <article
                key={entry.slug}
                id={entry.slug}
                className={`${styles.entry} ${isNewest ? styles.entryNewest : ''}`}
              >
                <time
                  className={styles.dateColumn}
                  dateTime={entry.date.toISOString().slice(0, 10)}
                >
                  <span aria-hidden="true" className={styles.dateDay}>
                    {entry.date.getDate()}
                  </span>
                  <span aria-hidden="true" className={styles.dateMonth}>
                    {formatMesCorto(entry.date)}
                  </span>
                  <span className={styles.srOnly}>{formatFechaEsAr(entry.date)}</span>
                </time>

                <div className={styles.rail}>
                  <span className={styles.dot} />
                  <span className={styles.line} />
                </div>

                <div className={styles.card}>
                  {(isNewest || entry.area) && (
                    <div className={styles.metaRow}>
                      {isNewest && <span className={styles.newBadge}>Nuevo</span>}
                      {entry.area && <span className={styles.areaTag}>{entry.area}</span>}
                    </div>
                  )}
                  <h2 className={styles.entryTitle}>{entry.title}</h2>
                  <div className={styles.entryBody} dangerouslySetInnerHTML={{ __html: html }} />
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
