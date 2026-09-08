import path from 'path';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, '.', '');
    return {
      server: {
        port: 3000,
        host: '0.0.0.0',
      },
      plugins: [react()],
      define: {
        'process.env.API_KEY': JSON.stringify(env.GEMINI_API_KEY),
        'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY)
      },
      resolve: {
        alias: {
          '@': path.resolve(__dirname, '.'),
        }
      },
      build: {
        rollupOptions: {
          output: {
            manualChunks: {
              // Vendor chunks - split large dependencies
              'vendor-react': ['react', 'react-dom'],
              'vendor-markdown': ['react-markdown', 'remark-gfm', 'rehype-raw'],
              'vendor-analytics': ['posthog-js'],
              'vendor-zustand': ['zustand'],
              // Mermaid is already lazy-loaded with HowItWorks,
              // but we can ensure it's in its own chunk
              'vendor-mermaid': ['mermaid'],
            }
          }
        },
        // Increase warning limit since we're intentionally chunking
        chunkSizeWarningLimit: 600,
      }
    };
});
