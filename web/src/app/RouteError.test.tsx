import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RouteError } from './RouteError';

function Throws({ error }: { error: Error }): never {
  throw error;
}

// React reports a render error through the window's "error" event, which jsdom prints unless
// someone handles it. Here the crash is the point of the test, so it's handled (and kept quiet).
const quiet = (event: ErrorEvent) => {
  event.preventDefault();
};
beforeEach(() => {
  window.addEventListener('error', quiet);
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => {
  window.removeEventListener('error', quiet);
});

function renderFailingRoute(error: Error) {
  const router = createMemoryRouter([
    { path: '/', element: <Throws error={error} />, errorElement: <RouteError /> },
  ]);
  render(<RouterProvider router={router} />);
}

describe('the route error page', () => {
  it('says a page crashed, as an alert, and offers a reload', () => {
    renderFailingRoute(new TypeError("Cannot read properties of undefined (reading 'title')"));
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
  });

  it.each([
    'Failed to fetch dynamically imported module: https://example.com/assets/ChatPage-x1.js',
    'Importing a module script failed.', // Safari
    'error loading dynamically imported module', // Firefox
  ])('explains a page whose code is gone after a deploy (%s)', (message) => {
    renderFailingRoute(new TypeError(message));
    expect(screen.getByRole('heading', { name: "This page couldn't load" })).toBeInTheDocument();
    expect(screen.getByText(/may have been updated since you opened it/)).toBeInTheDocument();
  });
});
