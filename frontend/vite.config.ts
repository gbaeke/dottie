import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = `http://localhost:${process.env.PORT ?? '8370'}` // the backend's PORT (run-local.sh --dev)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  // in dev, Vite serves the app and hands the API and the sign-in to the backend
  server: { proxy: { '/api': backend, '/auth': backend } },
})
