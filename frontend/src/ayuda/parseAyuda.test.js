import { describe, it, expect } from 'vitest';
import { parseAyuda, filtrarAyuda } from './loadAyuda';

const TICKETS = `# Tickets

Área: Tickets
Ruta: Tickets → Tickets
Permiso: Pedile a un administrador acceso a Tickets.

## Para qué sirve

Sirve para **seguir** los pedidos internos.
`;

const DESIGNER = `# Designer

Área: Documentos
Ruta: Documentos → Designer
Permiso: Acceso a Designer.

## Para qué sirve

Diseñar plantillas de impresión.
`;

const INDICE = `# Índice de la ayuda

| # | Pantalla | Archivo |
|---|----------|---------|
| 1 | Designer | \`designer.md\` |
| 2 | Tickets | \`tickets.md\` |
| 3 | Configuración tickets | \`configuracion-tickets.md\` |
`;

describe('parseAyuda', () => {
  it('reads the title, Área, Ruta and Permiso, and leaves them out of the body', () => {
    const [grupo] = parseAyuda({ './tickets.md': TICKETS });
    const [seccion] = grupo.secciones;

    expect(grupo.area).toBe('Tickets');
    expect(seccion).toMatchObject({
      slug: 'tickets',
      title: 'Tickets',
      area: 'Tickets',
      ruta: 'Tickets → Tickets',
      permiso: 'Pedile a un administrador acceso a Tickets.',
    });
    expect(seccion.bodyMarkdown).not.toMatch(/Área:|Ruta:|Permiso:|# Tickets\n/);
    expect(seccion.bodyMarkdown).toContain('Sirve para **seguir** los pedidos internos.');
  });

  it('demotes the body headings two levels, under the área and section headings', () => {
    const [grupo] = parseAyuda({ './tickets.md': TICKETS });
    expect(grupo.secciones[0].bodyMarkdown).toMatch(/^#### Para qué sirve$/m);
  });

  it('never shows _indice.md or README.md as a section', () => {
    const grupos = parseAyuda({ './_indice.md': INDICE, './README.md': '# Readme', './tickets.md': TICKETS });
    const slugs = grupos.flatMap((g) => g.secciones.map((s) => s.slug));
    expect(slugs).toEqual(['tickets']);
  });

  it('groups sections by Área in the order of _indice.md (the menu order)', () => {
    const grupos = parseAyuda({
      './tickets.md': TICKETS,
      './configuracion-tickets.md': TICKETS.replace('# Tickets', '# Configuración tickets'),
      './designer.md': DESIGNER,
      './_indice.md': INDICE,
    });

    expect(grupos.map((g) => g.area)).toEqual(['Documentos', 'Tickets']);
    expect(grupos[1].secciones.map((s) => s.slug)).toEqual(['tickets', 'configuracion-tickets']);
  });

  it('puts screens missing from the index last, by title, and a missing Área under "Otras pantallas"', () => {
    const grupos = parseAyuda({
      './_indice.md': INDICE,
      './tickets.md': TICKETS,
      './zeta.md': '# Zeta\n\nTexto.',
      './alfa.md': '# Alfa\n\nÁrea: Tickets\n\nTexto.',
    });

    expect(grupos.map((g) => g.area)).toEqual(['Tickets', 'Otras pantallas']);
    expect(grupos[0].secciones.map((s) => s.slug)).toEqual(['tickets', 'alfa']);
    expect(grupos[1].secciones.map((s) => s.slug)).toEqual(['zeta']);
  });
});

describe('filtrarAyuda', () => {
  const grupos = parseAyuda({ './_indice.md': INDICE, './tickets.md': TICKETS, './designer.md': DESIGNER });

  it('returns every section for an empty search', () => {
    expect(filtrarAyuda(grupos, '  ')).toBe(grupos);
  });

  it('matches titles and text ignoring case and accents, and drops áreas left empty', () => {
    const porTitulo = filtrarAyuda(grupos, 'DESIGNER');
    expect(porTitulo.map((g) => g.area)).toEqual(['Documentos']);

    const porTexto = filtrarAyuda(grupos, 'disenar plantillas');
    expect(porTexto.flatMap((g) => g.secciones.map((s) => s.slug))).toEqual(['designer']);

    const porTextoConMarkdown = filtrarAyuda(grupos, 'seguir los pedidos');
    expect(porTextoConMarkdown.flatMap((g) => g.secciones.map((s) => s.slug))).toEqual(['tickets']);

    expect(filtrarAyuda(grupos, 'no existe en ningún lado')).toEqual([]);
  });
});
