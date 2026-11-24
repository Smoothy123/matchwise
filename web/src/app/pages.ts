import { lazy } from 'react';

// Each page is its own JavaScript chunk, downloaded the first time someone opens it. The import()
// calls are kept in one object so the nav can start downloading a page on hover or focus.
export const pageLoaders = {
  chat: () => import('../features/chat/ChatPage'),
  matches: () => import('../features/matches/MatchesPage'),
  preferences: () => import('../features/preferences/PreferencesPage'),
  search: () => import('../features/search/SearchPage'),
  evals: () => import('../features/evals/EvalsPage'),
};

export type PageName = keyof typeof pageLoaders;

export const ChatPage = lazy(pageLoaders.chat);
export const MatchesPage = lazy(pageLoaders.matches);
export const PreferencesPage = lazy(pageLoaders.preferences);
export const SearchPage = lazy(pageLoaders.search);
export const EvalsPage = lazy(pageLoaders.evals);

/** Start downloading a page's code before it's needed. import() caches, so repeats are free. */
export function prefetchPage(page: PageName): void {
  pageLoaders[page]().catch(() => {
    // Ignored here: if the download really fails, opening the page shows the error.
  });
}
