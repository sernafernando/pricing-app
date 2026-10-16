/**
 * Opt-in permission codes: SUPERADMIN does NOT get these implicitly.
 *
 * They change how the app looks or which data it shows (the TP-Link theme, the
 * TP-only data lock), so a SUPERADMIN has one only when it was granted
 * explicitly (it then arrives in the `permisos` list from the backend).
 * Mirrors OPT_IN_PERMISSION_CODES in backend/app/services/permisos_service.py;
 * permisosOptIn.test.js keeps both lists equal.
 */
export const PERMISOS_OPT_IN = Object.freeze(['tplink.tema', 'tplink.solo']);

export const esPermisoOptIn = (codigo) => PERMISOS_OPT_IN.includes(codigo);
