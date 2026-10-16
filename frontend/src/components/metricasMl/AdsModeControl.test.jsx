import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdsModeControl from './AdsModeControl';

describe('AdsModeControl', () => {
  it('shows the three positions with the current one pressed', () => {
    render(<AdsModeControl value="mla" onChange={() => {}} />);
    const group = screen.getByRole('group', { name: 'Publicidad' });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sin publicidad' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Restar Ads de publicaciones' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Restar toda la publicidad' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('reports the position the operator picks', async () => {
    const onChange = vi.fn();
    render(<AdsModeControl value="off" onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Restar toda la publicidad' }));
    expect(onChange).toHaveBeenCalledWith('todo');
  });

  it('describes what the chosen position subtracts', () => {
    const { rerender } = render(<AdsModeControl value="off" onChange={() => {}} />);
    expect(screen.getByText('No se resta publicidad de Total Gauss ni del markup.')).toBeInTheDocument();
    rerender(<AdsModeControl value="mla" onChange={() => {}} />);
    expect(
      screen.getByText('Resta del Total Gauss y del markup solo los Ads atribuidos a cada publicación.'),
    ).toBeInTheDocument();
    rerender(<AdsModeControl value="todo" onChange={() => {}} />);
    expect(
      screen.getByText(
        'Resta del Total Gauss y del markup los Ads de cada publicación y además Display, Brand Ads y Ads sin producto.',
      ),
    ).toBeInTheDocument();
  });
});
