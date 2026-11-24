/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Matchwise API, e.g. http://localhost:8000. The only frontend setting. */
  readonly VITE_API_URL?: string;
  /** "true" builds the demo: responses recorded from the real API, no backend. See lib/demo.ts. */
  readonly VITE_DEMO_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
