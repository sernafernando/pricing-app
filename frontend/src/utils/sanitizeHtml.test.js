/**
 * Tests for sanitizeHtml (DOMPurify-based frontend HTML sanitizer).
 *
 * jsdom caveat (design section 6.4): nested mXSS / foreign-content payloads
 * (SVG/MathML/`noscript`/`template`) exercise HTML-parser namespace
 * switching. jsdom's parser (parse5) is spec-compliant but historically
 * diverges from live browser parsers in these foreign-content edge cases.
 * Therefore these tests assert only on robust output markers (absence of
 * `onerror`/`onload`/`<script`/disallowed tags), NOT exact serialized DOM
 * structure. They are a regression guard on our config + hook, not proof of
 * browser mXSS parity (that parity is covered by DOMPurify's own upstream
 * browser test suite).
 */
import { describe, it, expect } from 'vitest';
import { sanitizeHtml } from './sanitizeHtml';
import { sanitizeMessageHtml } from '../components/claimTranslations';

describe('sanitizeHtml — XSS neutralization', () => {
  it('X1 strips <script> tag and content', () => {
    const out = sanitizeHtml('<p>hi<script>alert(1)</script></p>');
    expect(out.toLowerCase()).not.toContain('<script');
    expect(out).toContain('hi');
  });

  it('X2 strips uppercase <SCRIPT> tag (case-insensitive)', () => {
    const out = sanitizeHtml('<SCRIPT>alert(1)</SCRIPT>');
    expect(out.toLowerCase()).not.toContain('<script');
  });

  it('X3 neutralizes <img onerror=...>', () => {
    const out = sanitizeHtml('<img src=x onerror=alert(1)>');
    expect(out.toLowerCase()).not.toContain('<img');
    expect(out.toLowerCase()).not.toContain('onerror');
  });

  it('X4 neutralizes <svg onload=...>', () => {
    const out = sanitizeHtml('<svg onload=alert(1)></svg>');
    expect(out.toLowerCase()).not.toContain('<svg');
    expect(out.toLowerCase()).not.toContain('onload');
  });

  it('X5 strips <iframe>', () => {
    const out = sanitizeHtml('<iframe src="javascript:alert(1)"></iframe>');
    expect(out.toLowerCase()).not.toContain('<iframe');
  });

  it('X6 strips <object>/<embed>', () => {
    const out1 = sanitizeHtml('<object data="x"></object>');
    const out2 = sanitizeHtml('<embed src="x">');
    expect(out1.toLowerCase()).not.toContain('<object');
    expect(out2.toLowerCase()).not.toContain('<embed');
  });

  it('X7 nested mXSS: no onerror/onload/<script/<svg/<style/<img survive', () => {
    const out = sanitizeHtml(
      '<svg><style><img src=x onerror=alert(1)></style></svg>',
    );
    const lower = out.toLowerCase();
    expect(lower).not.toContain('onerror');
    expect(lower).not.toContain('onload');
    expect(lower).not.toContain('<script');
    expect(lower).not.toContain('<svg');
    expect(lower).not.toContain('<style');
    expect(lower).not.toContain('<img');
  });

  it('X8 neutralizes javascript: href', () => {
    const out = sanitizeHtml('<a href="javascript:alert(1)">click</a>');
    expect(out.toLowerCase()).not.toContain('javascript:');
    expect(out).toContain('click');
  });

  it('X9 neutralizes data: href with embedded script', () => {
    const out = sanitizeHtml(
      '<a href="data:text/html,<script>alert(1)</script>">click</a>',
    );
    const lower = out.toLowerCase();
    expect(lower).not.toContain('data:text/html');
    expect(lower).not.toContain('<script');
  });

  it('X10 <p onclick=...> keeps tag/text, strips onclick', () => {
    const out = sanitizeHtml('<p onclick="alert(1)">hi</p>');
    expect(out).toContain('<p>');
    expect(out.toLowerCase()).not.toContain('onclick');
    expect(out).toContain('hi');
  });

  it('X11 strips onmouseover but keeps href + forced target/rel', () => {
    const out = sanitizeHtml('<a href="https://ok.com" onmouseover="alert(1)">x</a>');
    expect(out.toLowerCase()).not.toContain('onmouseover');
    expect(out).toContain('href="https://ok.com"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
  });
});

describe('sanitizeHtml — legitimate content preserved', () => {
  it('P1 preserves <b>', () => {
    expect(sanitizeHtml('<b>bold</b>')).toContain('<b>bold</b>');
  });

  it('P2 preserves <br>', () => {
    expect(sanitizeHtml('line<br>break')).toContain('<br');
  });

  it('P3 preserves <strong>/<em>/<i>/<u>', () => {
    const out = sanitizeHtml('<strong>s</strong><em>e</em><i>i</i><u>u</u>');
    expect(out).toContain('<strong>s</strong>');
    expect(out).toContain('<em>e</em>');
    expect(out).toContain('<i>i</i>');
    expect(out).toContain('<u>u</u>');
  });

  it('P4 preserves <p>/<ul>/<ol>/<li>', () => {
    const out = sanitizeHtml('<p>para</p><ul><li>item</li></ul><ol><li>first</li></ol>');
    expect(out).toContain('<p>para</p>');
    expect(out).toContain('<ul>');
    expect(out).toContain('<li>item</li>');
    expect(out).toContain('<ol>');
    expect(out).toContain('<li>first</li>');
  });

  it('P5 https link survives with forced target/rel', () => {
    const out = sanitizeHtml('<a href="https://example.com">link text</a>');
    expect(out).toContain('href="https://example.com"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain('link text');
  });

  it('P6 http link survives', () => {
    const out = sanitizeHtml('<a href="http://example.com">link text</a>');
    expect(out).toContain('href="http://example.com"');
  });

  it('P7 attacker-supplied target/rel overridden, not merged', () => {
    const out = sanitizeHtml(
      '<a href="https://example.com" target="_self" rel="opener">link</a>',
    );
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).not.toContain('_self');
    expect(out).not.toContain('rel="opener"');
  });

  it('P8 non-http(s) href stripped, text preserved (ftp)', () => {
    const out = sanitizeHtml('<a href="ftp://example.com">click</a>');
    expect(out.toLowerCase()).not.toContain('href="ftp');
    expect(out).toContain('click');
  });

  it('P9 non-http(s) href stripped, text preserved (vbscript)', () => {
    const out = sanitizeHtml('<a href="vbscript:alert(1)">click</a>');
    expect(out.toLowerCase()).not.toContain('vbscript:');
    expect(out).toContain('click');
  });
});

describe('sanitizeHtml — empty contract', () => {
  it('empty string returns empty string', () => {
    expect(sanitizeHtml('')).toBe('');
  });

  it('null returns empty string', () => {
    expect(sanitizeHtml(null)).toBe('');
  });

  it('undefined returns empty string', () => {
    expect(sanitizeHtml(undefined)).toBe('');
  });
});

describe('sanitizeMessageHtml — delegation contract', () => {
  it('matches sanitizeHtml output for a representative payload', () => {
    const payload = '<p>Hello <b>world</b></p><a href="https://x.com">x</a>';
    expect(sanitizeMessageHtml(payload)).toBe(sanitizeHtml(payload));
  });

  it('returns empty string for null (preserves ClaimCards fallback contract)', () => {
    expect(sanitizeMessageHtml(null)).toBe('');
  });
});
