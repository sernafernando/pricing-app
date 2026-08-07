import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProvenanceBadge from './ProvenanceBadge';

/**
 * SC (spec: Provenance Is Always Visible): `humano` vs `ia_confirmada` vs
 * `ia_auto` must each render a VISIBLY DISTINCT badge — not just present/
 * absent, but distinguishable from each other. `ia_auto` is reserved for a
 * future auto-apply flag, currently unused, but must still render distinctly
 * if a value carries it.
 */
describe('ProvenanceBadge', () => {
  it('renders a distinct label for humano', () => {
    render(<ProvenanceBadge origen="humano" />);
    expect(screen.getByText('Manual')).toBeInTheDocument();
  });

  it('renders a distinct label for ia_confirmada', () => {
    render(<ProvenanceBadge origen="ia_confirmada" />);
    expect(screen.getByText('IA confirmada')).toBeInTheDocument();
  });

  it('renders a distinct label for ia_auto (reserved, unused today)', () => {
    render(<ProvenanceBadge origen="ia_auto" />);
    expect(screen.getByText('IA automática')).toBeInTheDocument();
  });

  it('the three origins render with different CSS classes (not just different text)', () => {
    const { container: humano } = render(<ProvenanceBadge origen="humano" />);
    const { container: confirmada } = render(<ProvenanceBadge origen="ia_confirmada" />);
    const { container: auto } = render(<ProvenanceBadge origen="ia_auto" />);

    const classHumano = humano.querySelector('span').className;
    const classConfirmada = confirmada.querySelector('span').className;
    const classAuto = auto.querySelector('span').className;

    expect(classHumano).not.toBe(classConfirmada);
    expect(classConfirmada).not.toBe(classAuto);
    expect(classHumano).not.toBe(classAuto);
  });

  it('renders nothing for a null/unset origen (unclassified field)', () => {
    const { container } = render(<ProvenanceBadge origen={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
