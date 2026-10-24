import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend holds every API key; the browser only ever talks to it via /api.
    // GAE_API_TARGET lets a verification run point at its own backend port.
    proxy: {
      '/api': process.env.GAE_API_TARGET || 'http://127.0.0.1:8000',
    },
  },
})
