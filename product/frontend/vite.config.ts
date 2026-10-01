import path from 'path'
import { fileURLToPath } from 'url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Set VITE_API_PROXY_TARGET when the API is not on this host (e.g. Docker service).
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Prevent "dispatcher.useState" null crashes from duplicate React copies
    // (common with Vite prebundling + react-dom createPortal).
    dedupe: ['react', 'react-dom'],
    alias: {
      react: path.resolve(rootDir, 'node_modules/react'),
      'react-dom': path.resolve(rootDir, 'node_modules/react-dom'),
    },
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react/jsx-runtime'],
  },
  server: {
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0
      },
      '/mcp': {
        target: apiProxyTarget,
        changeOrigin: true,
        ws: true,
        timeout: 0,
        proxyTimeout: 0,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const contentType = String(proxyRes.headers['content-type'] || '')
            if (contentType.includes('text/event-stream')) {
              res.setHeader('Cache-Control', 'no-cache, no-transform')
              res.setHeader('Connection', 'keep-alive')
              res.setHeader('X-Accel-Buffering', 'no')
            }
          })
        }
      }
    }
  }
})
