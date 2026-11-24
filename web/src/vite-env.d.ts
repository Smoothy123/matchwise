/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Matchwise API, e.g. http://localhost:8000. The only frontend setting. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
