# Permiso para Auto-aplicación

**Fecha:** 2026-11-17

**Resumen ejecutivo:** el check de Auto-aplicación en Criterios (por publicación y en masa) solo lo ven quienes tienen el permiso `promos.auto_aplicacion`, otorgado a mano (no está en ningún rol).

## Qué cambia

1. Sin ese permiso no aparece el check; el resto de criterios sigue igual.
2. Con permiso, mismo comportamiento de antes (responsabilidad al activarlo).
3. Se asigna en la administración de permisos del usuario (override), no por rol.
