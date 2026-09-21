/**
 * Novedades loader (odd/tasks/novedades-changelog.md, T1).
 *
 * Entries are Markdown files named `YYYY-MM-DD-<slug>.md` under
 * `frontend/src/novedades/`. The pure parsing/sorting logic lives here as
 * `parseNovedades`, which takes a `{ filename: rawMarkdown }` map so it is
 * unit-testable without touching Vite's `import.meta.glob`.
 *
 * Filename contract: only `YYYY-MM-DD-<slug>.md` is valid (strict 4-2-2
 * digit groups). Anything else — `README.md`, a malformed date like
 * `2026-9-1-x.md`, etc. — is silently skipped, never thrown on: authors are
 * non-engineers, a typo in a filename must not break the page for everyone.
 */

const FILENAME_RE = /^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$/;
const H1_RE = /^#\s+(.+)$/m;
// Matches an optional "Área: X" (or unaccented "Area: X") line, case-insensitive.
const AREA_RE = /^[ÁA]rea:\s*(.+)$/i;

/**
 * Parses and sorts entries from a raw `{ filename: markdownSource }` map.
 * Newest first by date, slug as a stable tie-break (descending, so entries
 * sharing a date get a deterministic, repeatable order).
 *
 * @param {Record<string, string>} rawByFilename
 * @returns {Array<{ slug: string, date: Date, title: string, bodyMarkdown: string, area: string | null }>}
 */
export function parseNovedades(rawByFilename) {
  const entries = [];

  for (const [key, raw] of Object.entries(rawByFilename || {})) {
    // import.meta.glob keys are relative paths ("./2026-09-21-x.md").
    const filename = key.split('/').pop();
    const match = filename.match(FILENAME_RE);
    if (!match) continue;

    const [, year, month, day, slug] = match;
    const monthIndex = Number(month) - 1;
    const date = new Date(Number(year), monthIndex, Number(day));
    // Guard against out-of-range calendar values (e.g. month 13, day 32)
    // that `Date` silently rolls over into the next month/year.
    if (
      date.getFullYear() !== Number(year) ||
      date.getMonth() !== monthIndex ||
      date.getDate() !== Number(day)
    ) {
      continue;
    }

    const h1Match = raw.match(H1_RE);
    const title = h1Match ? h1Match[1].trim() : slug;
    let bodyMarkdown = h1Match
      ? raw.slice(0, h1Match.index) + raw.slice(h1Match.index + h1Match[0].length)
      : raw;
    bodyMarkdown = bodyMarkdown.trim();

    // Optional "Área: X" tag line: only recognized when it is literally the
    // first non-empty line of the body (not skipped-to further down).
    let area = null;
    const bodyLines = bodyMarkdown.split('\n');
    let firstNonEmptyIndex = -1;
    for (let i = 0; i < bodyLines.length; i += 1) {
      if (bodyLines[i].trim() !== '') {
        firstNonEmptyIndex = i;
        break;
      }
    }
    if (firstNonEmptyIndex !== -1) {
      const areaMatch = bodyLines[firstNonEmptyIndex].trim().match(AREA_RE);
      if (areaMatch) {
        area = areaMatch[1].trim();
        bodyLines.splice(firstNonEmptyIndex, 1);
        bodyMarkdown = bodyLines.join('\n').trim();
      }
    }

    entries.push({
      slug,
      date,
      title,
      bodyMarkdown,
      area,
    });
  }

  entries.sort((a, b) => {
    const dateDiff = b.date.getTime() - a.date.getTime();
    if (dateDiff !== 0) return dateDiff;
    return b.slug.localeCompare(a.slug);
  });

  return entries;
}

// Vite-native raw import, eager so entries are available synchronously.
// No plugin, no frontmatter library — see odd/tasks/novedades-changelog.md.
const rawModules = import.meta.glob('./*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
});

export function loadNovedades() {
  return parseNovedades(rawModules);
}
