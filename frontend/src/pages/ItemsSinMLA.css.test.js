import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import process from 'node:process';

// Vitest runs from the frontend root; `?raw` CSS imports come back empty here.
const css = readFileSync(resolve(process.cwd(), 'src/pages/ItemsSinMLA.css'), 'utf8');

const selectorLists = [...css.matchAll(/([^{}]+)\{[^{}]*\}/g)].map(([, selectors]) =>
  selectors.replace(/\/\*[\s\S]*?\*\//g, '').split(',').map((s) => s.trim()).filter(Boolean),
);

describe('ItemsSinMLA store badge selectors', () => {
  it('every selector of a light-theme rule carries the light-theme prefix (no dark-mode leak)', () => {
    const lightRules = selectorLists.filter((list) => list.some((s) => s.includes('data-theme="light"')));
    expect(lightRules.length).toBeGreaterThan(0);
    for (const list of lightRules) {
      for (const selector of list) expect(selector).toContain('data-theme="light"');
    }
  });

  it('the new TP-Link id has a light-theme rule too', () => {
    const light = selectorLists.flat().filter((s) => s.includes('data-theme="light"') && s.includes('471846'));
    expect(light.length).toBeGreaterThanOrEqual(2);
  });
});
