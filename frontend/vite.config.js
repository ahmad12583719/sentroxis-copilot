import fs from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const httpsKey = process.env.VITE_HTTPS_KEY
const httpsCert = process.env.VITE_HTTPS_CERT
const https = httpsKey && httpsCert && fs.existsSync(httpsKey) && fs.existsSync(httpsCert)
  ? { key: fs.readFileSync(httpsKey), cert: fs.readFileSync(httpsCert) }
  : undefined

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    https,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      // Keep the browser-facing host and HTTPS origin intact. Velociraptor is
      // configured with this same base path, so its CSRF cookie is first-party.
      '/velociraptor-console': {
        target: 'https://127.0.0.1:8889',
        secure: false,
        ws: true,
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/tests/setup.js',
    css: true,
  },
})
