import { createBrowserRouter, createMemoryRouter, type RouteObject } from 'react-router';

import { Layout } from './Layout';
import { NotFound } from './NotFound';
import { ChatPage, EvalsPage, MatchesPage, PreferencesPage, SearchPage } from './pages';
import { RouteError } from './RouteError';

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      {
        // Errors inside a page (including a page chunk that fails to download) show here, inside
        // the layout, so the header and nav stay usable.
        errorElement: <RouteError />,
        children: [
          { index: true, element: <ChatPage /> },
          { path: 'matches', element: <MatchesPage /> },
          { path: 'preferences', element: <PreferencesPage /> },
          { path: 'search', element: <SearchPage /> },
          { path: 'evals', element: <EvalsPage /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}

/** For tests: the same routes, starting at `path`, without touching the real URL. */
export function createTestRouter(path = '/') {
  return createMemoryRouter(routes, { initialEntries: [path] });
}
