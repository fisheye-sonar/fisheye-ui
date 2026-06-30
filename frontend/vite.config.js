import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../fisheye_ui/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/jobs': {
        target: 'http://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
