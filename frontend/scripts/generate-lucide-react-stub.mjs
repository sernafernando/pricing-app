#!/usr/bin/env node
/**
 * Regenerates `src/test/lucide-react-stub.jsx` from every named import of
 * `lucide-react` under `src/`. Run after adding a new lucide icon import:
 *
 *   node scripts/generate-lucide-react-stub.mjs
 *
 * See docs/vitest-unit-oom-diagnosis.md (Fix A).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, '..');
const srcRoot = path.join(frontendRoot, 'src');
const outFile = path.join(srcRoot, 'test', 'lucide-react-stub.jsx');

const blockRe = /import\s*\{([^}]+)\}\s*from\s*['"]lucide-react['"]/gs;
const identRe = /^[A-Za-z_][A-Za-z0-9_]*$/;

function walk(dir, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, files);
    else if (/\.(js|jsx|ts|tsx)$/.test(entry.name)) files.push(full);
  }
  return files;
}

const names = new Set();
for (const file of walk(srcRoot)) {
  // Do not scan the stub itself for imports.
  if (path.resolve(file) === outFile) continue;
  const text = fs.readFileSync(file, 'utf8');
  if (!text.includes('lucide-react')) continue;
  for (const match of text.matchAll(blockRe)) {
    for (const part of match[1].split(',')) {
      const token = part.trim();
      if (!token || token.startsWith('//')) continue;
      const base = token.split(/\s+as\s+/)[0].trim();
      if (!identRe.test(base)) {
        throw new Error(`Unexpected lucide import token ${JSON.stringify(token)} in ${file}`);
      }
      names.add(base);
    }
  }
}

const sorted = [...names].sort();
if (sorted.length === 0) {
  throw new Error('No lucide-react named imports found under src/');
}

const header = `/**
 * Lightweight lucide-react stub for the Vitest *unit* project only.
 *
 * GENERATED — do not edit by hand. Regenerate with:
 *   node scripts/generate-lucide-react-stub.mjs
 *
 * Why: unit setup used to \`importOriginal()\` the full lucide catalog into
 * every worker; that contributed to CI OOM near the end of the ~399-file
 * suite. See docs/vitest-unit-oom-diagnosis.md (Fix A).
 *
 * Each export is a distinct forwardRef component so identity assertions
 * (e.g. getCategoryIcon → Laptop) keep working. Props mirror lucide enough
 * for a11y queries (\`role="img"\` + \`aria-label\`) and \`svg.lucide-*\` selectors:
 * map \`size\` → width/height, default \`aria-hidden\` only when no a11y props.
 */
import { forwardRef, createElement } from 'react'

function toKebab(name) {
  return name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').replace(/([A-Z])([A-Z][a-z])/g, '$1-$2').toLowerCase()
}

function icon(name) {
  const Comp = forwardRef(function LucideStub(props, ref) {
    const {
      size = 24,
      color = 'currentColor',
      strokeWidth = 2,
      absoluteStrokeWidth,
      className,
      ...rest
    } = props
    const hasA11y =
      rest['aria-label'] != null ||
      rest['aria-labelledby'] != null ||
      rest.role != null
    const width = size
    const height = size
    const resolvedStroke = absoluteStrokeWidth
      ? (Number(strokeWidth) * 24) / Number(size)
      : strokeWidth
    return createElement('svg', {
      ref,
      xmlns: 'http://www.w3.org/2000/svg',
      width,
      height,
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: color,
      strokeWidth: resolvedStroke,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      className: ['lucide', \`lucide-\${toKebab(name)}\`, className].filter(Boolean).join(' '),
      ...(hasA11y ? {} : { 'aria-hidden': true }),
      ...rest,
    })
  })
  Comp.displayName = name
  return Comp
}

`;

const body = sorted.map((n) => `export const ${n} = icon('${n}')`).join('\n') + '\n';
fs.writeFileSync(outFile, header + body);
console.log(`Wrote ${sorted.length} exports → ${path.relative(frontendRoot, outFile)}`);
