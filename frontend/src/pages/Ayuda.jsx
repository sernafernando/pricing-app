import { useEffect, useMemo, useState } from 'react';
import { BookOpen, Search } from 'lucide-react';
import { marked } from 'marked';
import { loadAyuda, filtrarAyuda } from '../ayuda/loadAyuda';
import { sanitizeHtml } from '../utils/sanitizeHtml';
import styles from './Ayuda.module.css';

// Prose tags a help section needs beyond the shared sanitizeHtml default
// allowlist (strong/b/em/i/u/br/p/ul/ol/li/a). Body headings are demoted by
// the loader to h3-h6, and a few screens explain their columns in a table.
const MARKDOWN_EXTRA_TAGS = [
  'h3',
  'h4',
  'h5',
  'h6',
  'code',
  'pre',
  'blockquote',
  'hr',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
];

// Áreas like "Otras pantallas" have spaces, which an id cannot hold.
function idArea(area) {
  return `area-${area.toLowerCase().replace(/\s+/g, '-')}`;
}

/**
 * Ayuda — end-user help manual: one section per screen, grouped by the
 * menu área, with a search over titles and text. Visible to every
 * logged-in user, like Novedades. Content lives in `frontend/src/ayuda/`.
 */
export default function Ayuda() {
  const grupos = useMemo(() => loadAyuda(), []);
  const [busqueda, setBusqueda] = useState('');

  // Rendered once: the search only hides sections, it never re-parses them.
  const htmlPorSlug = useMemo(() => {
    const map = new Map();
    for (const grupo of grupos) {
      for (const s of grupo.secciones) {
        map.set(s.slug, sanitizeHtml(marked.parse(s.bodyMarkdown), { extraTags: MARKDOWN_EXTRA_TAGS }));
      }
    }
    return map;
  }, [grupos]);

  const visibles = useMemo(() => filtrarAyuda(grupos, busqueda), [grupos, busqueda]);
  const cantidad = visibles.reduce((total, grupo) => total + grupo.secciones.length, 0);
  const termino = busqueda.trim();

  // A link like /ayuda#tickets opens on that section.
  useEffect(() => {
    const hash = window.location.hash.replace('#', '');
    if (!hash) return;
    document.getElementById(hash)?.scrollIntoView({ block: 'start' });
  }, []);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <p className={styles.eyebrow}>
          <BookOpen size={14} aria-hidden="true" />
          Manual de uso
        </p>
        <h1 className={styles.title}>Ayuda</h1>
        <p className={styles.subtitle}>
          Para qué sirve cada pantalla, dónde está y cómo se usa. Buscá una palabra o elegila en el índice.
        </p>
        <label className={styles.search}>
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar en la ayuda..."
            aria-label="Buscar en la ayuda"
          />
        </label>
        {termino && (
          <p className={styles.resultados}>
            {cantidad === 0
              ? `Ninguna sección coincide con “${termino}”.`
              : `${cantidad} ${cantidad === 1 ? 'sección' : 'secciones'}`}
          </p>
        )}
      </div>

      {grupos.length === 0 ? (
        <div className={styles.empty}>Todavía no hay ayuda cargada.</div>
      ) : (
        <div className={styles.layout}>
          <nav className={styles.indice} aria-label="Índice de la ayuda">
            {visibles.map((grupo) => (
              <div key={grupo.area} className={styles.indiceGrupo}>
                <span className={styles.indiceArea}>{grupo.area}</span>
                <ul>
                  {grupo.secciones.map((s) => (
                    <li key={s.slug}>
                      <a href={`#${s.slug}`}>{s.title}</a>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>

          <div className={styles.contenido}>
            {visibles.map((grupo) => (
              <section key={grupo.area} className={styles.area} aria-labelledby={idArea(grupo.area)}>
                <h2 id={idArea(grupo.area)} className={styles.areaTitulo}>
                  {grupo.area}
                </h2>
                {grupo.secciones.map((s) => (
                  <article key={s.slug} id={s.slug} className={styles.seccion}>
                    <h3 className={styles.seccionTitulo}>{s.title}</h3>
                    {(s.ruta || s.permiso) && (
                      <dl className={styles.meta}>
                        {s.ruta && (
                          <div>
                            <dt>Dónde está</dt>
                            <dd>{s.ruta}</dd>
                          </div>
                        )}
                        {s.permiso && (
                          <div>
                            <dt>Acceso</dt>
                            <dd>{s.permiso}</dd>
                          </div>
                        )}
                      </dl>
                    )}
                    <div className={styles.cuerpo} dangerouslySetInnerHTML={{ __html: htmlPorSlug.get(s.slug) }} />
                  </article>
                ))}
              </section>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
