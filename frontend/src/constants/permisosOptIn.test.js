/**
 * The opt-in list exists twice (frontend checks and backend service). Keep them
 * equal by reading the backend constant straight from its source file.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PERMISOS_OPT_IN, esPermisoOptIn } from './permisosOptIn';

const BACKEND_SERVICE = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../backend/app/services/permisos_service.py',
);

const backendOptIn = () => {
  const source = fs.readFileSync(BACKEND_SERVICE, 'utf8');
  const match = source.match(/OPT_IN_PERMISSION_CODES\s*=\s*frozenset\(\{([^}]*)\}\)/);
  if (!match) throw new Error('OPT_IN_PERMISSION_CODES not found in permisos_service.py');
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort();
};

describe('opt-in permission codes', () => {
  it('match the backend OPT_IN_PERMISSION_CODES', () => {
    expect([...PERMISOS_OPT_IN].sort()).toEqual(backendOptIn());
  });

  it('esPermisoOptIn tells opt-in codes apart', () => {
    expect(esPermisoOptIn('tplink.tema')).toBe(true);
    expect(esPermisoOptIn('tplink.solo')).toBe(true);
    expect(esPermisoOptIn('productos.ver')).toBe(false);
  });
});
