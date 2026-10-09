/**
 * Publicaciones ML is a route behind `ml_ops.ver` (publicaciones-ml-vista S71.1).
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
  it('S71.1: is a route behind ml_ops.ver', () => {
    expect(appSource).toMatch(
      /\{ path: '\/ml-publicaciones', component: PublicacionesML, permiso: 'ml_ops\.ver' \}/,
    );
    expect(appSource).toMatch(/PublicacionesML = lazy\(\(\) => import\('\.\/pages\/PublicacionesML'\)\)/);
  });

  it('P14: is discoverable from the Sidebar and SmartRedirect, announced by exactly one novedad', () => {
    expect(sidebarSource).toContain('/ml-publicaciones');
    expect(smartRedirectSource).toContain('/ml-publicaciones');
    const mentions = Object.entries(novedades).filter(([, text]) => /ml-publicaciones|Publicaciones ML/i.test(text));
    expect(mentions.map(([file]) => file)).toEqual(['./novedades/2026-10-09-publicaciones-ml.md']);
  });
});
