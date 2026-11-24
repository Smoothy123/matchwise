import react from '@vitejs/plugin-react';
import { searchForWorkspaceRoot } from 'vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  // The API's CORS_ORIGINS allows exactly these ports. Without strictPort, Vite would quietly
  // move to 5174 when 5173 is busy, and every API call would then fail with a CORS error.
  server: {
    port: 5173,
    strictPort: true,
    // The Evals page imports the committed eval results from ../evals/results at build time.
    // The dev server only serves files inside web/ unless a folder is allowed here.
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), '../evals/results'] },
  },
  preview: { port: 4173, strictPort: true },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              // The libraries every page needs, in their own chunk: its hash only changes when
              // they're upgraded, so browsers keep it cached across deploys of the app code.
              // Only these: a catch-all node_modules group would pull visx (used by the Evals
              // page alone) into a chunk that every page loads.
              name: 'vendor',
              test: /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|@tanstack)[\\/]/,
            },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Vitest blanks CSS by default; tokens.test.ts reads the real tokens to check contrast.
    css: { include: [/tokens\.css/] },
    restoreMocks: true,
    unstubGlobals: true,
  },
});
