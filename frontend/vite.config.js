import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const wazuhDashboardProxy = {
  target: 'https://127.0.0.1:443',
  changeOrigin: true,
  secure: false,
  ws: true,
  rewrite: (path) => path.replace(/^\/wazuh-dashboard/, '') || '/',
  configure: (proxy) => {
    proxy.on('proxyRes', (proxyResponse) => {
      // Wazuh/OpenSearch sends SAMEORIGIN, which blocks the dashboard when
      // Sentroxis is served on port 5173. The proxy makes both pages same-origin.
      delete proxyResponse.headers['x-frame-options']
      delete proxyResponse.headers['content-security-policy']
      if (proxyResponse.headers.location) {
        proxyResponse.headers.location = proxyResponse.headers.location.replace(/^\//, '/wazuh-dashboard/')
      }
    })
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/wazuh-dashboard': wazuhDashboardProxy,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/tests/setup.js',
    css: true,
  },
})

// The proxy is intentionally development/local-only. Production deployments
// should terminate TLS and enforce an explicit frame-ancestors policy at the
// reverse proxy instead of disabling browser framing headers broadly.
