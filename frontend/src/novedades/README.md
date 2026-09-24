# Novedades

Each `.md` file in this folder is an entry on the **Novedades** page (`/novedades`), which users open from the sidebar or from a deploy alert.

## What goes here

**New features and how to use them.** Nothing else.

- ✅ A new tab, a new flow, a new button that changes how someone works.
- ❌ Bugfixes, refactors, performance work, internal changes. Those belong in commits and PRs, not here.

If a user would not notice the change, it does not need an entry.

## How to add one

1. Create `YYYY-MM-DD-<slug>.md` in this folder.
   - The date is the deploy date, and it is what orders the page (newest first).
   - The slug is the anchor: the entry is reachable at `/novedades#<slug>`.
   - Files that do not match the pattern (like this README) are ignored.
2. The first line is the title, as a single `# ` heading.
3. Write it for the person who uses the feature, not for a developer. Spanish, plain language. Say who built it if relevant.
4. Right after the optional `Área` / “Desarrollado por …” lines, include a short **Resumen ejecutivo** (a few lines, no jargon dump). It is for people who will not read the rest: what changed and what they should notice. Put it as high as possible, before “Cómo se usa”.
5. Include a **"Cómo se usa"** section with concrete steps: where to click and what they will see.
6. Ship the entry **in the same PR as the feature**, so it is reviewed with the code and goes live with the deploy.

No code change is needed: the page picks up new files at build time.

## Announcing it

After the deploy, create an alert on the alerts admin page (`/gestion/alertas`, sidebar entry **Alertas**, requires the `alertas.gestionar` permission):

- Message: one line about what is new.
- Action button label (`action_label`): `Ver cómo se usa`
- Action button URL (`action_url`): `/novedades#<slug>`
- Recipients (`roles_destinatarios`): `*` for everyone, or the roles that use the feature.

The alert system already tracks who dismissed each alert, so nobody sees it twice.

## Rendering

Entries are rendered with `marked` and sanitized with DOMPurify, so raw HTML such as `<script>` or `onerror=` is stripped. Stick to plain Markdown.

## Optional area tag

Right after the `# ` title, you can add a line `Área: <name>` (accents optional, e.g. `Area: Compras`). It renders as a small tag pill on the entry card and is removed from the rendered body — it must be the very first non-empty line after the title, or it is treated as regular body text.

## Tip boxes

A `> ` blockquote renders as a highlighted tip box. Use it to call out something the reader should double-check or pay extra attention to.
