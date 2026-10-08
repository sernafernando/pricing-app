/**
 * Publicaciones ML ships HIDDEN (publicaciones-ml-vista P11a.T6, S71.1/S72.1):
 * a route behind `ml_ops.ver`, reachable by URL only. Discovery (Sidebar item,
 * SmartRedirect entry, novedad) arrives with the go-live PR, not before.
 *
 * `App.jsx` keeps its route table private, so the contract is read from the
 * sources that would have to change to expose the screen.
 */
import { describe, it, expect } from 'vitest';
import appSource from './App.jsx?raw';
import sidebarSource from './components/Sidebar.jsx?raw';
import smartRedirectSource from './components/SmartRedirect.jsx?raw';

const novedades = import.meta.glob('./novedades/*', { query: '?raw', import: 'default', eager: true });

describe('Publicaciones ML hidden route', () => {
  it('S71.1: is a route behind ml_ops.ver', () => {
    expect(appSource).toMatch(
      /\{ path: '\/ml-publicaciones', component: PublicacionesML, permiso: 'ml_ops\.ver' \}/,
    );
    expect(appSource).toMatch(/PublicacionesML = lazy\(\(\) => import\('\.\/pages\/PublicacionesML'\)\)/);
  });

  it('S72.1: has no Sidebar entry, no SmartRedirect entry and no novedad', () => {
    expect(sidebarSource).not.toContain('ml-publicaciones');
    expect(smartRedirectSource).not.toContain('ml-publicaciones');
    const mentions = Object.entries(novedades).filter(([, text]) => /ml-publicaciones|Publicaciones ML/i.test(text));
    expect(mentions.map(([file]) => file)).toEqual([]);
  });
});
