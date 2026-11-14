import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    strictPort: true,
    proxy: {'/api': {
      target: 'http://127.0.0.1:5190', changeOrigin: true,
      configure(proxy) {
        proxy.on('proxyReq', (outgoing, incoming) => {
          // Forward only the known local dev page's same-origin requests.
          if (['http://127.0.0.1:5173', 'http://localhost:5173'].includes(incoming.headers.origin || ''))
            outgoing.setHeader('origin', 'http://127.0.0.1:5190');
        });
      },
    }},
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          flow: ['@xyflow/react'],
          icons: ['lucide-react'],
        },
      },
    },
  },
});
