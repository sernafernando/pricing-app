# Content-Security-Policy — Rollout Plan (audit ALTO-02)

**Status:** allowlist vetted from the codebase (2026-07-06). **Not yet deployed.**
CSP is defense-in-depth for the frontend XSS surface already narrowed by DOMPurify (PR #845): DOMPurify sanitizes MercadoLibre claim/order message HTML; CSP contains anything that escapes.

## Why this is an infra task, not a code PR

Deployment topology: **Cloudflare Tunnel → nginx → static SPA**. There is no nginx/Cloudflare config in this repo — the static build is served entirely by infrastructure outside it.

- A `<meta http-equiv="Content-Security-Policy">` tag in `frontend/index.html` **can** deliver an *enforcing* policy in-repo, but it **cannot** express `Content-Security-Policy-Report-Only`, `report-uri`/`report-to`, or `frame-ancestors`.
- The **safe** rollout requires an observation period in **Report-Only** mode, which only a response **header** can express → this must be set at nginx or Cloudflare by the infra owner.

**Do NOT ship an enforcing meta CSP blind.** A missed source silently breaks the app (a map with no tiles, a font that won't load, Zebra printing). Observe first, enforce second.

## Recommended sequence

1. **Infra owner** sets a `Content-Security-Policy-Report-Only` header (policy below) at nginx/Cloudflare for 1–2 weeks, with a `report-uri`/`report-to` endpoint (or Cloudflare's built-in reporting).
2. Monitor violation reports. Every legitimate source that shows up must be added to the policy (or the offending load fixed — see the prerequisite below).
3. Once reports are clean, promote to **enforcing** — either the header at infra (preferred: also gets `frame-ancestors`) or bake the vetted policy into the `index.html` meta tag in this repo.

## Prerequisite — DONE (this PR)

`frontend/src/components/turbo/MapaEnvios.jsx` and `frontend/src/components/MapaEnviosFlex.jsx` previously loaded Leaflet marker icons from external hosts (`cdnjs.cloudflare.com` default markers; `raw.githubusercontent.com/pointhi/leaflet-color-markers/master/...` colored markers — unversioned `master`, a supply-chain risk).

**Fixed:** default markers now import the bundled `leaflet/dist/images/*` from the npm package (matching `Empleados.jsx`); the 3 colored markers are vendored locally at a pinned commit under `frontend/src/assets/leaflet-markers/` (see its `ATTRIBUTION.md`). No map component loads icons from an external host anymore — so `cdnjs.cloudflare.com` and `raw.githubusercontent.com` are **already excluded** from the `img-src` below.

## Vetted policy (built from the actual code inventory)

```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' data: https://*.tile.openstreetmap.org;
connect-src 'self' http://localhost:9100;
worker-src 'self';
manifest-src 'self';
frame-ancestors 'none';
base-uri 'self';
object-src 'none';
```

### Directive notes

| Directive | Sources | Why |
|-----------|---------|-----|
| `script-src` | `'self'` | No inline `<script>`, no `eval`/`new Function` anywhere in `frontend/src`. Vite emits external JS only. |
| `style-src` | `'self' 'unsafe-inline' https://fonts.googleapis.com` | Heavy React `style={{…}}` usage requires `'unsafe-inline'` for styles. Google Fonts stylesheet. CSS Modules are self. |
| `font-src` | `'self' https://fonts.gstatic.com` | Google Fonts files. |
| `img-src` | `'self' data:` + `https://*.tile.openstreetmap.org` | `data:` for inline SVG markers/icons; OSM tile servers for Leaflet maps. **After the prerequisite**, no cdnjs / raw.githubusercontent needed. |
| `connect-src` | `'self' http://localhost:9100` | API (`VITE_API_URL`) + SSE (`${API_BASE}/sse/stream`) are same-origin. `localhost:9100` = Zebra Browser Print — see mixed-content caveat. |
| `frame-ancestors` | `'none'` | No legitimate embedding. Header-only (meta can't set it). |
| `object-src` | `'none'` | No `<object>`/`<embed>`. |

### Open caveats to resolve during Report-Only

- **Zebra print (`http://localhost:9100`)**: active mixed content (HTTPS page → HTTP fetch) is already blocked by browsers independent of CSP. Verify in devtools whether Zebra printing works in production today at all before attributing any breakage to CSP. If it's already broken, this is a separate fix (audit MEDIO-03: use Zebra's HTTPS Browser Print endpoint).
- If the prerequisite (local marker icons) is **not** done first, add `https://cdnjs.cloudflare.com https://raw.githubusercontent.com` to `img-src` — but prefer fixing the source.

## Verification (manual, no browser test harness exists)

After enabling Report-Only, click through and watch the console for CSP reports:
- Leaflet tiles: open Empleados / GestionZonas (map with OSM tiles).
- External marker icons: open MapaEnvios / MapaEnviosFlex (until the prerequisite lands).
- Sanitized HTML: open a claim/RMA card.
- Zebra: attempt a label print.
- SSE: confirm the live notification stream connects.
- Google Fonts: confirm fonts render.
