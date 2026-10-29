# Ayuda

Each `.md` file in this folder is one screen's section on the **Ayuda** page (`/ayuda`), the end-user help manual. Every logged-in user can open it from the sidebar, next to Novedades.

## When to update it

A PR that changes what a screen shows (a new button, a column, a tab, a message, a filter) updates that screen's file **in the same PR**, the same way a feature ships its novedad. A novedad says what is new; the Ayuda section says how the screen works today, so it is edited in place instead of piling up entries.

## File format

```markdown
# <Screen name, as the menu shows it>

Área: <the menu group: Productos, Operaciones, Reportes...>
Ruta: <where to find it, e.g. Productos → Productos>
Permiso: <what access it needs, in plain words>

## Para qué sirve

## Cómo se usa
```

- The `Área`, `Ruta` and `Permiso` lines go right after the title. The page groups sections by `Área`. A file without `Área` lands under **Otras pantallas**.
- The file name is the anchor: `tickets.md` is reachable at `/ayuda#tickets`.
- Write for the person using the screen, in Spanish. Quote the labels exactly as the screen shows them, in **bold**.
- Plain Markdown only. Raw HTML is stripped when the page renders.

## Order and index

`_indice.md` lists every screen in menu order. The page follows that order: áreas in the order their first screen appears, screens in the index order. A new screen gets a row in `_indice.md`. Files starting with `_` and this README never show on the page.
