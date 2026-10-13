import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import AvatarIniciales from './AvatarIniciales';

const iniciales = (nombre) => render(<AvatarIniciales nombre={nombre} />).container.textContent;

describe('AvatarIniciales', () => {
  it('shows the first two initials in upper case', () => {
    expect(iniciales('ana  maría pérez')).toBe('AM');
  });

  it.each([[''], ['   '], [null], [undefined]])('falls back to "?" for an empty name (%j)', (nombre) => {
    expect(iniciales(nombre)).toBe('?');
  });

  it('keeps a name that starts with an emoji as one whole character', () => {
    expect(iniciales('😀 Ana')).toBe('😀A');
  });
});
