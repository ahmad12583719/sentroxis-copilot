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
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/tests/setup.js',
    css: true,
  },
})
