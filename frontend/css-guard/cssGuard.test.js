/**
 * The ratchet, and the proof that it is not vacuous.
 *
 * `pnpm run lint:css` answers "did anyone ADD a violation?". These tests answer
 * what stylelint structurally cannot: "is the allowlist still TRUE?". Without
 * that, the list rots — entries survive the cleanup that made them obsolete,
 * the grandfathered surface quietly grows back, and the guard is decoration.
 *
 * Both halves compare the SET of offending files to the SET of allowlisted
 * files and demand exact equality, catching both directions at once:
 *   - offender not on the list  -> a NEW violation was introduced
 *   - listed file not offending -> a STALE entry, cleanup left half-done
 */

import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import stylelint from 'stylelint';
import {
  CONTROL_BOX_ALLOWLIST,
  HARDCODED_COLOR_ALLOWLIST,
  TOKEN_DEFINITION_FILES,
} from './allowlist.js';
import { colorRules } from '../stylelint.config.js';
import {
  FRONTEND_ROOT,
  findControlBoxOffenders,
  findControlCssFiles,
  isControlClass,
  scanControlBoxViolations,
} from './scan.js';

const sorted = (values) => [...values].sort();

/** Difference both ways, reported as an actionable message. */
const diff = (actual, allowed, ruleLabel) => {
  const actualSet = new Set(actual);
  const allowedSet = new Set(allowed);
  return {
    added: sorted(actual.filter((f) => !allowedSet.has(f))),
    stale: sorted(allowed.filter((f) => !actualSet.has(f))),
    ruleLabel,
  };
};

const assertRatchet = ({ added, stale, ruleLabel }) => {
  expect(
    added,
    `NEW ${ruleLabel} violation(s). Fix the CSS — do NOT add these to the allowlist:\n  ${added.join('\n  ')}`,
  ).toEqual([]);
  expect(
    stale,
    `STALE ${ruleLabel} allowlist entr(ies): these files no longer violate. Delete them from css-guard/allowlist.js:\n  ${stale.join('\n  ')}`,
  ).toEqual([]);
};

describe('rule 1 — colors come from design tokens (stylelint)', () => {
  it('allowlist matches reality exactly', async () => {
    // Rules ON everywhere, allowlist NOT applied: this is what makes stale
    // entries visible. The shipped config suppresses exactly these files.
    const { results } = await stylelint.lint({
      cwd: FRONTEND_ROOT,
      files: 'src/**/*.css',
      config: { rules: colorRules, ignoreFiles: TOKEN_DEFINITION_FILES },
    });

    const offenders = results
      .filter((result) => result.warnings.length > 0)
      .map((result) => path.relative(FRONTEND_ROOT, result.source).split(path.sep).join('/'));

    assertRatchet(diff(offenders, HARDCODED_COLOR_ALLOWLIST, 'hardcoded-color'));
  }, 60_000);

  it('detects a hardcoded color, so a silent no-op cannot make this vacuous', async () => {
    const { results } = await stylelint.lint({
      code: '.x { color: #bada55; background: rgb(1, 2, 3); border-color: red; }',
      config: { rules: colorRules },
    });
    expect(results[0].warnings.map((w) => w.rule).sort()).toEqual([
      'color-named',
      'color-no-hex',
      'declaration-property-value-disallowed-list',
    ]);
  });

  it('accepts tokens, and token-derived alpha, and OS-owned system colors', async () => {
    const { results } = await stylelint.lint({
      code: `.x { color: var(--cf-text-primary); background: rgba(var(--brand-primary-rgb), 0.1); }
             @media (forced-colors: active) { .y { color: CanvasText; border-color: ButtonText; outline-color: Highlight; } }`,
      config: { rules: colorRules },
    });
    expect(results[0].warnings).toEqual([]);
  });
});

describe('rule 2 — form controls do not hand-roll their box (composes instead)', () => {
  it('allowlist matches reality exactly', () => {
    const offenders = [...findControlBoxOffenders().keys()];
    assertRatchet(diff(offenders, CONTROL_BOX_ALLOWLIST, 'control-box'));
  });

  it('detects each owned property, so the scan cannot silently become a no-op', () => {
    for (const property of ['padding', 'border-radius', 'background', 'background-color']) {
      expect(
        scanControlBoxViolations(`.searchInput { ${property}: 4px 8px; }`),
        `expected \`${property}\` on a control class to be flagged`,
      ).not.toEqual([]);
    }
  });

  it('allows the sanctioned escape hatch and unrelated properties', () => {
    expect(
      scanControlBoxViolations(
        `.input { composes: field from '../styles/forms.css'; width: 100%; color: var(--cf-text-primary); }`,
      ),
    ).toEqual([]);
  });

  it('separates real controls from state and layout classes', () => {
    // Measured false positives of a naive substring match. Flagging these is
    // how the rule would earn a reputation for being wrong and get deleted.
    for (const stateClass of ['rowSelected', 'selectionBar', 'selectorItem', 'btnMultiSelectAction']) {
      expect(isControlClass(stateClass), `${stateClass} is not a form control`).toBe(false);
    }
    for (const control of ['input', 'select', 'textarea', 'filterSelect', 'searchInput', 'formTextarea']) {
      expect(isControlClass(control), `${control} IS a form control`).toBe(true);
    }
  });

  it('discovers module CSS anywhere under src/, not in a fixed folder list', () => {
    const discovered = findControlCssFiles();
    const onDisk = [];
    const walk = (dir) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith('.module.css')) onDisk.push(full);
      }
    };
    walk(path.join(FRONTEND_ROOT, 'src'));

    const stylesDir = path.join(FRONTEND_ROOT, 'src', 'styles') + path.sep;
    expect(sorted(discovered)).toEqual(sorted(onDisk.filter((f) => !f.startsWith(stylesDir))));
    expect(discovered.length).toBeGreaterThan(100);
    // Directories the walk must reach without being told they exist.
    for (const dir of ['src/pages', 'src/components']) {
      expect(discovered.some((f) => f.includes(path.join(...dir.split('/'))))).toBe(true);
    }
  });
});
