/**
 * CSS convention guard — discovery + the control-box scanner.
 *
 * Why this exists: AGENTS.md has long said form controls arrive via
 * `composes:`. Nothing enforced it, so the tree drifted to 56 CSS modules each
 * defining their own `.input` — 19 different `padding` values, 6 different
 * `border-radius` values, and the same form fixed by hand three times.
 *
 * Discovery deliberately WALKS all of `src/` and matches on file NAME rather
 * than enumerating directories, mirroring
 * `backend/tests/unit/test_pxq_base_price_boundary.py` — the one guard here
 * that has actually held. An earlier version of that test listed directories,
 * missed `app/routers/`, and stayed green while the thing it guarded slipped
 * past. A name-based walk cannot develop that blind spot.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import postcss from 'postcss';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const FRONTEND_ROOT = path.resolve(HERE, '..');
const SRC_ROOT = path.join(FRONTEND_ROOT, 'src');

/** Repo-relative, POSIX-separated — the form used by the allowlists. */
export const toRelative = (absolutePath) =>
  path.relative(FRONTEND_ROOT, absolutePath).split(path.sep).join('/');

/** Every `.css` under `src/`, by extension, wherever it lives. */
export const findCssFiles = (root = SRC_ROOT) => {
  const found = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.css')) found.push(full);
    }
  };
  walk(root);
  return found.sort();
};

/**
 * The files rule 2 polices: CSS Modules OUTSIDE `src/styles/`, where the owned
 * primitives live. Those are ALLOWED to declare control box styling — it is
 * their whole job. Everyone else must `composes:` from them.
 */
export const findControlCssFiles = (root = SRC_ROOT) =>
  findCssFiles(root).filter(
    (file) =>
      file.endsWith('.module.css') &&
      !file.startsWith(path.join(root, 'styles') + path.sep),
  );

const CLASS_IN_SELECTOR = /\.(-?[A-Za-z_][A-Za-z0-9_-]*)/g;

/** The box properties that belong to the owned primitive, not to callers. */
const OWNED_BOX_PROPERTY = /^(?:padding|border-radius|background|background-color)$/i;

const CONTROL_WORDS = new Set(['input', 'select', 'textarea']);

/**
 * Words marking a class as LAYOUT or ACTION rather than the control itself.
 * Measured, not guessed: a naive `/input|select|textarea/i` substring match
 * flagged `.rowSelected`, `.selectionBtnBorrar`, `.selectionBar` and
 * `.selectorItem` — state and button classes unrelated to control drift. A
 * rule that blocks `.rowSelected { background }` gets deleted within a week,
 * so precision here is survival, not polish.
 */
const NEVER_A_CONTROL = new Set(['btn', 'button']);
const WRAPPER_TAIL = new Set([
  'group', 'wrapper', 'wrap', 'container', 'row', 'box', 'label', 'field',
  'section', 'header', 'footer', 'list', 'options', 'option', 'item', 'grid',
  'col', 'cell', 'bar', 'panel', 'title', 'hint', 'error', 'icon', 'dropdown',
  'menu', 'area', 'display',
]);

/** `multiSelectSearchInput` -> ['multi','select','search','input'] */
const splitWords = (className) =>
  className
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((word) => word.toLowerCase());

/**
 * True when the class names an actual form control. Matches whole camelCase
 * WORDS, not substrings — that is what separates `.filterSelect` (a control)
 * from `.selected` / `.selection` / `.selector` (state).
 */
export const isControlClass = (className) => {
  const words = splitWords(className);
  if (!words.some((word) => CONTROL_WORDS.has(word))) return false;
  if (words.some((word) => NEVER_A_CONTROL.has(word))) return false;
  return !WRAPPER_TAIL.has(words[words.length - 1]);
};

/**
 * One description per offending declaration, empty when clean. Takes source
 * TEXT so it is testable against a synthetic string — see the non-vacuity tests.
 */
export const scanControlBoxViolations = (source, label = '<inline>') => {
  const violations = [];
  const root = postcss.parse(source, { from: label });

  root.walkRules((rule) => {
    const controls = [...rule.selector.matchAll(CLASS_IN_SELECTOR)]
      .map((match) => match[1])
      .filter(isControlClass);
    if (controls.length === 0) return;

    rule.walkDecls((decl) => {
      if (!OWNED_BOX_PROPERTY.test(decl.prop)) return;
      violations.push(
        `${label}: \`${rule.selector.replace(/\s+/g, ' ')}\` declares \`${decl.prop}\``,
      );
    });
  });

  return violations;
};

/** Repo-relative paths of every module CSS file that violates rule 2. */
export const findControlBoxOffenders = (root = SRC_ROOT) => {
  const offenders = new Map();
  for (const file of findControlCssFiles(root)) {
    const relative = toRelative(file);
    const violations = scanControlBoxViolations(
      fs.readFileSync(file, 'utf8'),
      relative,
    );
    if (violations.length > 0) offenders.set(relative, violations);
  }
  return offenders;
};
