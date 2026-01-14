import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/dispatch': {
        target: 'http://localhost:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    lib: {
      entry: 'src/index.ts',
      formats: ['es'],
      fileName: () => 'index.js'
    },
    rollupOptions: {
      // Externalize peer dependencies (parent provides them)
      external: ['react', 'react-dom', 'react-dom/client', 'react/jsx-runtime', '@wolffm/themes'],
      output: {
        assetFileNames: 'style.css'
      }
    },
    target: 'es2022',
    cssCodeSplit: false
  }
})
