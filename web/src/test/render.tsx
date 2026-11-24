import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider } from 'react-router';

import { createQueryClient } from '../api/queries';
import { createTestRouter } from '../app/router';

/**
 * The whole app at `path`, with a fresh cache built by the app's own createQueryClient, so tests
 * see the real caching (staleTime and friends). Only retries are off, so error states show at
 * once; the retry policy itself is unit-tested in queries.test.ts.
 */
export function renderApp(path = '/') {
  const queryClient = createQueryClient();
  const defaults = queryClient.getDefaultOptions();
  queryClient.setDefaultOptions({ ...defaults, queries: { ...defaults.queries, retry: false } });
  const router = createTestRouter(path);
  const user = userEvent.setup();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, queryClient, router, user };
}
