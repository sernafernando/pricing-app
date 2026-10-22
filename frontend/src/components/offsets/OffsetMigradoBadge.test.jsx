/**
 * OffsetMigradoBadge: a legacy offset migrated to a sell-out campaign says which one (T16); the rest say nothing.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import OffsetMigradoBadge from './OffsetMigradoBadge';

describe('OffsetMigradoBadge', () => {
  it('a migrated offset names its campaign and explains edits do not reach it', () => {
    render(<OffsetMigradoBadge campanaId={55} />);
    const badge = screen.getByText('Migrado a campaña #55');
    expect(badge).toHaveAttribute('title', expect.stringContaining('no se pasan a la campaña'));
  });

  it('renders nothing for an offset that was not migrated', () => {
    const { container } = render(<OffsetMigradoBadge campanaId={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
