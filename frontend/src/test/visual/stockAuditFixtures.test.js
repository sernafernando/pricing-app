/**
 * The audit fixtures must read like the backend's answers (owner 2026-11-18: the niveles screenshot showed a category
 * whose Full was twice its products'): a category is the exact sum of its product rows, a brand of its categories,
 * and the KPIs of any level are the sum of its top-level rows.
 */
import { describe, expect, it } from 'vitest';
import { stockAuditLevelResponse } from './stockAuditFixtures';

const PARTS = ['erp', 'full', 'total'];

function expectSum(group, children, label) {
  for (const part of PARTS) {
    const units = children.reduce((acc, c) => acc + c[part].unidades, 0);
    const usd = children.reduce((acc, c) => acc + (c[part].usd ?? 0), 0);
    expect(group[part].unidades, `${label} ${part} units`).toBe(units);
    expect(group[part].usd, `${label} ${part} usd`).toBeCloseTo(usd, 2);
  }
  const products = children.reduce((acc, c) => acc + (['marca', 'categoria'].includes(c.tipo) ? c.productos : 1), 0);
  expect(group.productos, `${label} productos`).toBe(products);
  for (const w of ['7d', '30d']) {
    const sold = children.reduce((acc, c) => acc + (c.ventas?.[`unidades_${w}`] ?? 0), 0);
    expect(group.ventas[`unidades_${w}`], `${label} ventas ${w}`).toBe(sold);
    const full = children.reduce((acc, c) => acc + (c.ventas?.envio?.[w]?.full ?? 0), 0);
    expect(group.ventas.envio[w].full, `${label} Full ${w}`).toBe(full);
    expect(group.ventas.envio[w].erp + group.ventas.envio[w].full, `${label} ERP+Full ${w}`).toBe(sold);
  }
}

const drill = (grupo) => ({
  ...(grupo.marca ? { grupo_marca: grupo.marca } : {}),
  ...(grupo.categoria ? { grupo_categoria: grupo.categoria } : {}),
});

describe('stock audit level fixtures', () => {
  it('every category is the exact sum of its visible product rows', () => {
    const brands = stockAuditLevelResponse({ nivel: 'marca' }).rows;
    const categories = brands.flatMap((b) => b.categorias);
    expect(categories.length).toBeGreaterThan(0);
    for (const c of categories) {
      const products = stockAuditLevelResponse({ nivel: 'producto', ...drill(c.grupo) }).rows;
      expect(products.length, c.key).toBeGreaterThan(0);
      expectSum(c, products, c.key);
    }
  });

  it('every brand is the exact sum of its categories', () => {
    for (const b of stockAuditLevelResponse({ nivel: 'marca' }).rows) expectSum(b, b.categorias, b.key);
  });

  it("a product's sales hold its variants' and packs' sales in base units, as the backend adds them", () => {
    const products = stockAuditLevelResponse({ nivel: 'producto' }).rows;
    for (const p of products.filter((r) => r.variantes?.length)) {
      for (const w of ['7d', '30d']) {
        const fromVariants = p.variantes.reduce((acc, v) => acc + (v.ventas?.[`unidades_${w}`] ?? 0) * (v.cantidad ?? 1), 0);
        expect(p.ventas[`unidades_${w}`], `${p.key} ${w}`).toBeGreaterThanOrEqual(fromVariants);
        const { erp, full } = p.ventas.envio[w];
        expect(erp + full, `${p.key} ERP+Full ${w}`).toBe(p.ventas[`unidades_${w}`]);
      }
    }
  });

  it.each(['marca', 'categoria', 'producto'])('the KPIs at nivel=%s are the sum of its top-level rows', (nivel) => {
    const body = stockAuditLevelResponse({ nivel });
    for (const part of PARTS) {
      expect(body.kpis[part].unidades, part).toBe(body.rows.reduce((acc, r) => acc + r[part].unidades, 0));
      expect(body.kpis[part].usd, part).toBeCloseTo(body.rows.reduce((acc, r) => acc + (r[part].usd ?? 0), 0), 2);
    }
  });
});
