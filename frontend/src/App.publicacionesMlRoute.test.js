/**
 * Publicaciones ML is a route behind `productos.ver` or `ml_ops.ver` (S71.1; S12f1 added Productos' permission).
 * It shipped hidden; the go-live PR (P14) added the discovery: the Sidebar item,
 * the SmartRedirect entry and exactly one novedad (R7). The Sidebar and
 * SmartRedirect behaviour is tested in their own suites.
 *
 * `App.jsx` keeps its route table private, so the contract is read from the
 * sources that would have to change to expose the screen.
 */
import { describe, it, expect } from 'vitest';
import appSource from './App.jsx?raw';
import sidebarSource from './components/Sidebar.jsx?raw';
import smartRedirectSource from './components/SmartRedirect.jsx?raw';

const novedades = import.meta.glob('./novedades/*', { query: '?raw', import: 'default', eager: true });

describe('Publicaciones ML route', () => {
  it("S12f1: is a route behind Productos' productos.ver or ml_ops.ver (any of them)", () => {
    expect(appSource).toMatch(
      /\{ path: '\/ml-publicaciones', component: PublicacionesML, permisos: \['productos\.ver', 'ml_ops\.ver'\] \}/,
    );
    expect(appSource).toMatch(/PublicacionesML = lazy\(\(\) => import\('\.\/pages\/PublicacionesML'\)\)/);
  });

  it('P14: is discoverable from the Sidebar and SmartRedirect, announced by exactly one novedad', () => {
    expect(sidebarSource).toContain('/ml-publicaciones');
    expect(smartRedirectSource).toContain('/ml-publicaciones');
    // Later novedades extend the screen and mention it too; the launch one comes first.
    const mentions = Object.entries(novedades)
      .filter(([, text]) => /ml-publicaciones|Publicaciones ML/i.test(text))
      .map(([file]) => file)
      .sort();
    expect(mentions[0]).toBe('./novedades/2026-10-09-publicaciones-ml.md');
  });
});
