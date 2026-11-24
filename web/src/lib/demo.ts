/**
 * Demo mode: a build that serves responses recorded from the real API instead of calling one
 * (VITE_DEMO_MODE=true). It exists so the app can be shown publicly without a backend, an LLM key
 * or an unauthenticated API on the internet, and it always says, on every page, that it is a
 * recording. A function, not a constant, so tests can switch it on with vi.stubEnv.
 */
import recording from '../demo/recorded/recording.json';

export function isDemo(): boolean {
  return import.meta.env.VITE_DEMO_MODE === 'true';
}

/** When the demo's responses were recorded from the real API. */
export const DEMO_RECORDED_AT: string = recording.recordedAt;

export const REPO_URL = 'https://github.com/Smoothy123/matchwise';
