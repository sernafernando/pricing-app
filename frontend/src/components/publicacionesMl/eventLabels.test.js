/**
 * eventLabels (publicaciones-ml-vista P13b.T1, S55.1/S55.2): every event type
 * the store really writes has a Spanish label, and a type nobody labelled yet
 * gets a generic Spanish one instead of its raw code.
 */
import { readFileSync } from 'node:fs';
import { cwd } from 'node:process';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { EVENT_LABELS, GENERIC_EVENT_LABEL, eventLabel } from './eventLabels';

/**
 * The real list: `EVENT_TYPES` of the backend's `events.py`, read from the
 * source (vitest runs from `frontend/`) so a type added there fails here until somebody labels it. Entries are
 * string literals or module constants (`PRICE_CHANGED = "price_changed"`).
 */
function realEventTypes() {
  const source = readFileSync(resolve(cwd(), '../backend/app/services/ml_publications/events.py'), 'utf8');
  const body = /EVENT_TYPES[^=]*=\s*\(([\s\S]*?)\n\)/.exec(source)?.[1] ?? '';
  return body
    .split('\n')
    .map((line) => line.replace(/#.*$/, '').trim().replace(/,$/, ''))
    .filter(Boolean)
    .map((token) => {
      const literal = /^"([^"]+)"$/.exec(token);
      if (literal) return literal[1];
      const constant = new RegExp(`^${token}\\s*=\\s*"([^"]+)"`, 'm').exec(source);
      if (!constant) throw new Error(`cannot resolve event type ${token}`);
      return constant[1];
    });
}

describe('the real event types', () => {
  const types = realEventTypes();

  it('reads the whole list, including the types the design omitted', () => {
    expect(types).toHaveLength(22);
    expect(types).toContain('listing_type_changed');
    expect(types).toContain('title_changed');
  });

  it.each(types)('%s has its own Spanish label (S55.1)', (type) => {
    expect(EVENT_LABELS[type]).toBeTruthy();
    expect(eventLabel(type)).toBe(EVENT_LABELS[type]);
    expect(eventLabel(type)).not.toBe(type);
    expect(eventLabel(type)).not.toBe(GENERIC_EVENT_LABEL);
  });

  it('labels nothing that is not a real type', () => {
    expect(Object.keys(EVENT_LABELS).sort()).toEqual([...types].sort());
  });
});

describe('an unmapped type', () => {
  it('shows a generic Spanish label, never the raw code (S55.2)', () => {
    expect(eventLabel('something_new')).toBe('Evento');
    expect(eventLabel(undefined)).toBe('Evento');
  });
});
