import path from 'path'
import { fileURLToPath } from 'url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Set VITE_API_PROXY_TARGET when the API is not on this host (e.g. Docker service).
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
const rootDir = path.dirname(fileURLToPath(import.meta.url))

function isOauthDiscoveryPath(url: string | undefined): boolean {
  const pathName = String(url || '').split('?')[0]
  return pathName.includes('/.well-known/oauth-') || pathName.includes('/.well-known/openid-configuration')
}

function stripWwwAuthenticate(proxy: { on: (event: string, fn: (...args: any[]) => void) => void }) {
  proxy.on('proxyRes', (proxyRes: { headers: Record<string, unknown> }) => {
    delete proxyRes.headers['www-authenticate']
  })
}

function noOauthDiscoveryPlugin() {
  return {
    name: 'astronote-no-oauth-discovery',
    configureServer(server: { middlewares: { use: (fn: (req: any, res: any, next: () => void) => void) => void } }) {
      server.middlewares.use((req, res, next) => {
        if (!isOauthDiscoveryPath(req.url)) {
          next()
          return
        }
        res.statusCode = 404
        res.setHeader('Content-Type', 'application/json')
        res.setHeader('Cache-Control', 'no-store')
        res.end(JSON.stringify({ error: 'not_found' }))
      })
    },
  }
}

export default defineConfig({
  plugins: [noOauthDiscoveryPlugin(), react()],
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
        proxyTimeout: 0,
        configure: stripWwwAuthenticate,
      },
      '/mcp': {
        target: apiProxyTarget,
        changeOrigin: true,
        ws: true,
        timeout: 0,
        proxyTimeout: 0,
        configure: (proxy) => {
          stripWwwAuthenticate(proxy)
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
