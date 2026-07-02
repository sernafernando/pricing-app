import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
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
          '**/RRHHHorasExtras-*.{js,css}',
          '**/DocumentDesigner-*.{js,css}',
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
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      }
    }
  }
})
