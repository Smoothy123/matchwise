import react from '@vitejs/plugin-react';
import { searchForWorkspaceRoot } from 'vite';
import { defineConfig } from 'vitest/config';

import vercel from './vercel.json' with { type: 'json' };

/**
 * The security headers the deployed site sends (vercel.json), also sent by `vite preview`, so the
 * local production preview, Lighthouse and the end-to-end tests all run under the real policy.
 * Locally the API is plain http on localhost, which the deployed policy (https only) would block,
 * so the preview adds it.
 */
function previewHeaders(): Record<string, string> {
  const site = vercel.headers.find((rule) => rule.source === '/(.*)');
  if (!site) throw new Error('vercel.json has no headers for "/(.*)"');
  const headers = Object.fromEntries(site.headers.map((h) => [h.key, h.value]));
  const api = process.env.VITE_API_URL ?? 'http://localhost:8000';
  const csp = headers['Content-Security-Policy'];
  if (csp)
    headers['Content-Security-Policy'] = csp.replace(
      "connect-src 'self' https:",
      `connect-src 'self' https: ${api}`,
    );
  return headers;
}

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
  preview: { port: 4173, strictPort: true, headers: previewHeaders() },
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
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      // main.tsx only runs in a real browser (it mounts the app): the Cypress tests cover it.
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/api/schema.gen.ts',
        'src/vite-env.d.ts',
        'src/main.tsx',
      ],
      reporter: ['text-summary', 'html'],
      // A little under today's numbers (96 / 87 / 96 / 98): enough to fail the build if a change
      // leaves new code untested, without failing it over one refactored line.
      thresholds: { statements: 95, branches: 85, functions: 93, lines: 95 },
    },
    unstubGlobals: true,
  },
});
