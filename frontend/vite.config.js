import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      workbox: {
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024, // 5 MiB — app bundles exceed default 2 MiB
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        cleanupOutdatedCaches: true,
        // API responses are NEVER cached by the service worker.
        // This is a business app with live data (pricing, sales, permissions):
        // serving a stale cached response silently is a correctness bug.
        // The previous NetworkFirst rule cached `/api/permisos/mis-permisos`,
        // which made sidebar items intermittently disappear on refresh because
        // a stale-but-complete permission set was served from cache.
        // Only the static app shell (globPatterns above) is precached.
        runtimeCaching: [
          {
            urlPattern: /^https?:\/\/.*\/api\//,
            handler: 'NetworkOnly',
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
