import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test/setup.ts'],
    exclude: ['**/node_modules/**', '**/e2e/**'],
  },
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'prompt',
      includeAssets: [
        'favicon.svg',
        'favicon.ico',
        'apple-touch-icon.png',
        'icon-192.png',
        'icon-384.png',
        'icon-512.png',
        'icon-1024.png',
        'icon-maskable-512.png',
        'brand/calcio-icon-primary.svg',
        'brand/calcio-icon-primary-512.png',
        'brand/calcio-icon-dark.svg',
        'brand/calcio-icon-gold.svg',
        'brand/calcio-mark.svg',
        'brand/calcio-mark-mono.svg',
        'brand/calcio-mark-gold.svg',
        'fonts/jetbrains-mono-600.woff2',
        'fonts/jetbrains-mono-700.woff2',
        'fonts/outfit-400.woff2',
        'fonts/outfit-600.woff2',
      ],
      manifest: {
        name: 'Calcio',
        short_name: 'Calcio',
        description: 'A private multi-league prediction app for tournament pools and season-long tables. Invite-only.',
        theme_color: '#071A3D',
        background_color: '#071A3D',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-384.png', sizes: '384x384', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-1024.png', sizes: '1024x1024', type: 'image/png' },
          { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    rollupOptions: {
      output: {
        // Only carve out chunks Vite ALWAYS preloads on the entry — react +
        // router + query are eagerly used by App.tsx. framer-motion and
        // recharts are only used by lazy routes, so leaving them out lets
        // Rollup keep them inside those routes' chunks instead of preloading
        // them on the unauth /login entry.
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'query': ['@tanstack/react-query'],
        },
      },
    },
  },
  server: {
    port: process.env['PORT'] ? parseInt(process.env['PORT']) : 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
