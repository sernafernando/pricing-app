import { describe, it, expect } from 'vitest';
import { parseNovedades } from './loadNovedades';

describe('parseNovedades', () => {
  it('parses date and slug from a valid filename', () => {
    const [entry] = parseNovedades({
      '2026-09-21-oc-match.md': '# OC Match\n\nBody text.',
    });
    expect(entry.slug).toBe('oc-match');
    expect(entry.date.getFullYear()).toBe(2026);
    expect(entry.date.getMonth()).toBe(8); // 0-indexed: September
    expect(entry.date.getDate()).toBe(21);
  });

  it('skips README.md (no date prefix)', () => {
    const entries = parseNovedades({
      'README.md': '# Not an entry',
    });
    expect(entries).toHaveLength(0);
  });

  it('skips a malformed date like 2026-9-1-x.md (not zero-padded)', () => {
    const entries = parseNovedades({
      '2026-9-1-x.md': '# Bad filename',
    });
    expect(entries).toHaveLength(0);
  });

  it('extracts the first H1 as the title and removes it from the body', () => {
    const [entry] = parseNovedades({
      '2026-01-01-example.md': '# My Title\n\nSome body content.',
    });
    expect(entry.title).toBe('My Title');
    expect(entry.bodyMarkdown).not.toContain('# My Title');
    expect(entry.bodyMarkdown).toContain('Some body content.');
  });

  it('falls back to the slug as the title when there is no H1', () => {
    const [entry] = parseNovedades({
      '2026-01-01-no-heading.md': 'Just some text, no heading.',
    });
    expect(entry.title).toBe('no-heading');
  });

  it('sorts newest first, with slug as a stable descending tie-break on the same date', () => {
    const entries = parseNovedades({
      '2026-01-01-alpha.md': '# Alpha',
      '2026-03-01-gamma.md': '# Gamma',
      '2026-01-01-beta.md': '# Beta',
      '2026-02-01-delta.md': '# Delta',
    });
    expect(entries.map((e) => e.slug)).toEqual(['gamma', 'delta', 'beta', 'alpha']);
  });
});
