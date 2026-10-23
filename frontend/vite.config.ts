import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend holds every API key; the browser only ever talks to it via /api.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
