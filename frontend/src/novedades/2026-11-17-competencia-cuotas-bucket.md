# Ver competencia: mismo tramo de cuotas

**Fecha:** 2026-11-17

**Resumen ejecutivo:** en **Publicaciones ML → Promos → Ver competencia**, el ranking del catálogo vuelve a limitar competidores al **mismo tipo de publicación y mismas cuotas** que la publicación abierta (por ejemplo Premium · 6 cuotas no mezcla 3 / 9 / 12). El arreglo aplica también a snapshots ya guardados, sin tener que pulsar **Actualizar**.

## Qué cambia

1. Corregimos el armado del “tramo” cuando MeLi manda las cuotas como número suelto (antes todo Premium caía en el mismo bucket).
2. El filtro se recalcula al **leer** el snapshot, así las consultas viejas se ven bien de inmediato.
3. **Clásica** vs **Premium** seguía ocultándose bien; el bug era entre distintas cuotas Premium.
