import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Package } from 'lucide-react';
import SaleItemThumbnail from './SaleItemThumbnail';

const PHOTO = 'https://http2.mlstatic.com/D_NQ_NP_1-O.jpg';

describe('SaleItemThumbnail', () => {
  it("shows the MLA's stored photo as is, lazily, instead of the placeholder", () => {
    const { container } = render(
      <SaleItemThumbnail url={PHOTO} className="box">
        <Package data-testid="placeholder" />
      </SaleItemThumbnail>,
    );
    const img = container.querySelector('img');
    expect(img).toHaveAttribute('src', PHOTO);
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
    expect(container.firstChild).toHaveClass('box');
  });

  it('without a photo keeps the placeholder', () => {
    const { container } = render(
      <SaleItemThumbnail url={null}>
        <Package data-testid="placeholder" />
      </SaleItemThumbnail>,
    );
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByTestId('placeholder')).toBeInTheDocument();
  });

  it('a photo that fails to load falls back to the placeholder', () => {
    const { container } = render(
      <SaleItemThumbnail url={PHOTO}>
        <Package data-testid="placeholder" />
      </SaleItemThumbnail>,
    );
    fireEvent.error(container.querySelector('img'));
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByTestId('placeholder')).toBeInTheDocument();
  });
});
