import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND_URL = process.env.VITE_API_BASE_URL || 'http://127.0.0.1:7860'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: BACKEND_URL, changeOrigin: true },
      '/stream': {
        target: BACKEND_URL,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache'
          })
        },
      },
      '/auth': { target: BACKEND_URL, changeOrigin: true },
      '/health': { target: BACKEND_URL, changeOrigin: true },
      '/arjun_profile.png': { target: BACKEND_URL, changeOrigin: true },
    },
  },
})
