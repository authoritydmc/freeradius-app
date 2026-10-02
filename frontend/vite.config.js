import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/radius/',
  build: {
    outDir: '../api/static/dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/[name].[hash].js',
        assetFileNames: 'assets/[name].[hash].[ext]'
      }
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/radius/api': {
        target: 'http://localhost:8090',
        changeOrigin: true
      },
      '/api': {
        target: 'http://localhost:8090',
        changeOrigin: true
      }
    }
  }
});
