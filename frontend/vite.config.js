import { defineConfig, configDefaults } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { playwright } from '@vitest/browser-playwright'

// Visual tests live in their own folder AND carry their own suffix. The suffix
// alone is not enough: `foo.visual.test.jsx` also matches vitest's default
// include glob, so without the explicit `exclude` below the jsdom project would
// pick these up and run layout assertions in an environment that has no layout.
const VISUAL_TESTS = 'src/test/visual/**/*.visual.test.jsx'

export default defineConfig({
  // TWO projects, never one. The jsdom suite is the repo's existing safety net
  // and must keep running byte-identically; the browser suite is additive.
  // They are selected by name from package.json scripts (`--project=unit` /
  // `--project=visual`) so neither can accidentally drag in the other:
  // running `pnpm test` must NOT require Playwright's browser binaries.
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: 'unit',
          environment: 'jsdom',
          globals: true,
          setupFiles: './src/test/setup.js',
          // jsdom computes no layout, so parsing CSS buys nothing but time.
          css: false,
          exclude: [...configDefaults.exclude, VISUAL_TESTS],
        },
      },
      {
        extends: true,
        // Pre-bundled up front. Discovering these mid-run makes Vite reload
        // the page, which vitest reports as "unexpectedly reloaded a test"
        // and which would restart assertions against a half-torn-down DOM.
        //
        // A VITE-level option, so it belongs on the project entry — NOT inside
        // `test`, where it used to sit. Vitest does not validate unknown keys
        // in `test`, so the old placement was silently dead: proven by putting
        // an unresolvable package in it, which produced no error at all, while
        // the same bogus entry here fails the run with "Failed to resolve
        // dependency: …, present in client 'optimizeDeps.include'".
        //
        // `test.deps.optimizer` is a different lever (it feeds the node-side
        // pools), and in Vitest 4 its keys are `client`/`ssr` — `web` was
        // renamed. Browser mode is served by a real Vite dev server, so Vite's
        // own `optimizeDeps` is the one that actually pre-bundles here.
        optimizeDeps: { include: ['axios', 'zustand', 'react/jsx-dev-runtime'] },
        test: {
          name: 'visual',
          include: [VISUAL_TESTS],
          globals: true,
          setupFiles: './src/test/visual/setup.visual.js',
          // The entire point: real CSS, so `composes:` chains and `var()`
          // tokens resolve the way they do in the browser.
          css: true,
          browser: {
            enabled: true,
            provider: playwright(),
            headless: true,
            // Fixed viewport: geometry assertions and screenshots are only
            // comparable if every run lays out at the same width.
            instances: [{ browser: 'chromium', viewport: { width: 1280, height: 800 } }],
            // A failing computed-style assertion is already fully diagnosed by
            // its message; an auto-captured PNG per failure is just noise.
            screenshotFailures: false,
          },
        },
      },
    ],
  },
  plugins: [
    react(),
    VitePWA({
      // 'prompt' (not autoUpdate): a new build does NOT silently reload the
      // page — that would wipe a half-filled form on a business app. Instead
      // the app surfaces a toast and the user applies the update on click.
      registerType: 'prompt',
      workbox: {
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024, // 5 MiB — app bundles exceed default 2 MiB
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        // Precache the app shell, but NOT the lazy route chunks or their heavy
        // vendor deps (pdf libs). These are code-split to load on demand, yet
        // the SW was downloading them for every user on install — e.g. the
        // RRHHHorasExtras chunk was requested when opening unrelated pages.
        // They are cached on-demand by the CacheFirst rule below instead.
        globIgnores: [
          '**/assets/lazy/**',
          '**/pdfmePlugins-*.js',
          '**/pdfmeFonts-*.js',
          '**/index.es-*.js',
        ],
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          // API responses are NEVER cached by the service worker.
          // This is a business app with live data (pricing, sales, permissions):
          // serving a stale cached response silently is a correctness bug.
          // The previous NetworkFirst rule cached `/api/permisos/mis-permisos`,
          // which made sidebar items intermittently disappear on refresh because
          // a stale-but-complete permission set was served from cache.
          //
          // The negative lookahead EXCLUDES `/api/sse/` so SSE streams are not
          // matched by any route and bypass the SW entirely — a service worker
          // proxying a long-lived EventSource stream breaks it (the connection
          // failed 3x and degraded to polling on every page).
          {
            urlPattern: /^https?:\/\/.*\/api\/(?!sse\/)/,
            handler: 'NetworkOnly',
          },
          // Build assets are content-hashed (immutable). Lazy chunks excluded
          // from precache get cached the first time they are actually loaded:
          // on-demand instead of upfront, and available offline afterwards.
          {
            urlPattern: /\/assets\/.*\.(?:js|css)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'app-assets',
              expiration: { maxEntries: 60, maxAgeSeconds: 30 * 24 * 60 * 60 },
            },
          },
        ],
      },
      manifest: {
        name: 'Gauss Online - Fichaje',
        short_name: 'Fichaje',
        description: 'Fichaje de entrada/salida para empleados',
        theme_color: '#1a1a2e',
        background_color: '#1a1a2e',
        display: 'standalone',
        start_url: '/fichaje',
        icons: [
          { src: '/favicon.png', sizes: '192x192', type: 'image/png' },
          { src: '/favicon.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
    }),
  ],
  server: {
    host: true,
    port: 5173,
    allowedHosts: ['pricing-app.gaussonline.com.ar'],
    proxy: {
      '/api': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        // Relocate code-split (lazy) chunks so the SW can exclude them from
        // precache with ONE glob. Does not change module→chunk assignment.
        chunkFileNames: (chunk) =>
          chunk.isDynamicEntry
            ? 'assets/lazy/[name]-[hash].js'
            : 'assets/[name]-[hash].js',
      },
    },
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      }
    }
  }
})
