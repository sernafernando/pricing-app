import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import PrearmadaBadge from './PrearmadaBadge';

const badgeOf = (exact, upgrade) => screen.getByLabelText(`Prearmadas — Exactas: ${exact} | Upgrade: ${upgrade}`);

describe('PrearmadaBadge', () => {
  it('outline keeps the words and the tooltip, and only adds its own look to the default one', () => {
    const { unmount } = render(<PrearmadaBadge stats={{ exact: 2, upgrade: 0 }} />);
    const filled = badgeOf(2, 0).className;
    expect(badgeOf(2, 0)).toHaveTextContent('2 listas');
    unmount();
    render(<PrearmadaBadge outline stats={{ exact: 2, upgrade: 0 }} />);
    expect(badgeOf(2, 0)).toHaveTextContent('2 listas');
    expect(badgeOf(2, 0)).toHaveAttribute('title', 'Prearmadas — Exactas: 2 | Upgrade: 0');
    expect(badgeOf(2, 0).className.startsWith(filled)).toBe(true);
    expect(badgeOf(2, 0).className).not.toBe(filled);
  });

  it('shows nothing without prearmadas, outline or not', () => {
    const { container } = render(<PrearmadaBadge outline stats={{ exact: 0, upgrade: 0 }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
