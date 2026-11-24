import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  // The API's CORS_ORIGINS allows exactly these ports. Without strictPort, Vite would quietly
  // move to 5174 when 5173 is busy, and every API call would then fail with a CORS error.
  server: { port: 5173, strictPort: true },
  preview: { port: 4173, strictPort: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Vitest blanks CSS by default; tokens.test.ts reads the real tokens to check contrast.
    css: { include: [/tokens\.css/] },
    restoreMocks: true,
    unstubGlobals: true,
  },
});
