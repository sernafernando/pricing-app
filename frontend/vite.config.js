import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
    },
    rollupOptions: {
      onwarn(warning, warn) {
        // pdfme usa eval internamente para expresiones de templates — es esperado
        if (warning.code === 'EVAL' && warning.id?.includes('@pdfme/')) return;
        warn(warning);
      },
    },
  }
})
