/**
 * Tests for Ayuda.jsx — the end-user help manual.
 *
 * `../ayuda/loadAyuda` keeps its real `filtrarAyuda` and only `loadAyuda` is
 * mocked, so tests control the sections independent of the real `.md` files.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import Ayuda from './Ayuda';

const mockLoadAyuda = vi.fn();

vi.mock('../ayuda/loadAyuda', async (importOriginal) => ({
  ...(await importOriginal()),
  loadAyuda: () => mockLoadAyuda(),
}));

const GRUPOS = [
  {
    area: 'Documentos',
    secciones: [
      {
        slug: 'designer',
        title: 'Designer',
        area: 'Documentos',
        ruta: 'Documentos → Designer',
        permiso: 'Acceso a Designer.',
        bodyMarkdown: '#### Para qué sirve\n\nDiseñar **plantillas** de impresión.',
      },
    ],
  },
  {
    area: 'Tickets',
    secciones: [
      {
        slug: 'tickets',
        title: 'Tickets',
        area: 'Tickets',
        ruta: 'Tickets → Tickets',
        permiso: 'Pedile a un administrador acceso a Tickets.',
        bodyMarkdown: 'Sirve para seguir los pedidos internos.',
      },
    ],
  },
];

beforeEach(() => {
  mockLoadAyuda.mockReturnValue(GRUPOS);
});

describe('Ayuda page', () => {
  it('renders each área with its sections: title, where to find it, permission and the Markdown body', () => {
    renderWithRouter(<Ayuda />);

    expect(screen.getByRole('heading', { level: 1, name: 'Ayuda' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Documentos' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Tickets' })).toBeInTheDocument();

    const seccion = document.getElementById('designer');
    expect(seccion.tagName).toBe('ARTICLE');
    const enSeccion = within(seccion);
    expect(enSeccion.getByRole('heading', { level: 3, name: 'Designer' })).toBeInTheDocument();
    expect(enSeccion.getByText('Documentos → Designer')).toBeInTheDocument();
    expect(enSeccion.getByText('Acceso a Designer.')).toBeInTheDocument();
    expect(enSeccion.getByRole('heading', { level: 4, name: 'Para qué sirve' })).toBeInTheDocument();
    expect(enSeccion.getByText('plantillas').tagName).toBe('STRONG');
  });

  it('lists every section in the index, linking to its anchor', () => {
    renderWithRouter(<Ayuda />);

    const indice = within(screen.getByRole('navigation', { name: 'Índice de la ayuda' }));
    expect(indice.getByRole('link', { name: 'Designer' })).toHaveAttribute('href', '#designer');
    expect(indice.getByRole('link', { name: 'Tickets' })).toHaveAttribute('href', '#tickets');
  });

  it('the search filters sections by title and text, and says when nothing matches', async () => {
    const user = userEvent.setup();
    renderWithRouter(<Ayuda />);
    const buscador = screen.getByRole('searchbox', { name: 'Buscar en la ayuda' });

    await user.type(buscador, 'pedidos internos');
    expect(document.getElementById('tickets')).not.toBeNull();
    expect(document.getElementById('designer')).toBeNull();
    expect(screen.queryByRole('heading', { level: 2, name: 'Documentos' })).not.toBeInTheDocument();
    expect(screen.getByText('1 sección')).toBeInTheDocument();

    await user.clear(buscador);
    await user.type(buscador, 'xyz inexistente');
    expect(screen.getByText('Ninguna sección coincide con “xyz inexistente”.')).toBeInTheDocument();
  });

  it('sanitizes the rendered body: no <script> element and no onerror attribute survive', () => {
    mockLoadAyuda.mockReturnValue([
      {
        area: 'Tickets',
        secciones: [
          {
            ...GRUPOS[1].secciones[0],
            bodyMarkdown: 'Hola <script>alert(1)</script> <img src=x onerror="alert(1)">',
          },
        ],
      },
    ]);
    renderWithRouter(<Ayuda />);

    const seccion = document.getElementById('tickets');
    expect(seccion.querySelector('script')).toBeNull();
    expect(seccion.querySelector('[onerror]')).toBeNull();
  });

  it('shows an empty state when there is no help yet', () => {
    mockLoadAyuda.mockReturnValue([]);
    renderWithRouter(<Ayuda />);
    expect(screen.getByText('Todavía no hay ayuda cargada.')).toBeInTheDocument();
  });
});
