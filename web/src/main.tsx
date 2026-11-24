import './styles/tokens.css';
import './styles/global.css';

import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';

import { createQueryClient } from './api/queries';
import { NAV_ITEMS } from './app/navigation';
import { prefetchPage } from './app/pages';
import { createAppRouter } from './app/router';

// Start downloading the code for the page being opened now, alongside React's own start-up,
// rather than after the first render asks for it. React.lazy then finds it already loading:
// import() returns the same promise for the same module.
const firstPage = NAV_ITEMS.find((item) => item.to === window.location.pathname)?.page;
if (firstPage) prefetchPage(firstPage);

const root = document.getElementById('root');
if (!root) throw new Error('index.html has no #root element');

const queryClient = createQueryClient();
const router = createAppRouter();

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
