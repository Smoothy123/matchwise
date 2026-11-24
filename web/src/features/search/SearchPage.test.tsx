import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { axeViolations } from '../../test/axe';
import { jsonResponse, mockApi } from '../../test/fetch';
import { HEALTHY, makeJob, makeResults } from '../../test/fixtures';
import { renderApp } from '../../test/render';
import { readLimit } from './SearchPage';

/** A fake search API; `delay` holds an answer back, to see what shows while it loads. */
function setup({ fail = false, delay = 0 } = {}) {
  const fetchMock = mockApi({
    'GET /health': HEALTHY,
    'GET /jobs/1000': makeJob({ id: 1000, title: 'python job 1' }),
    'GET /search': async (url: URL) => {
      if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
      if (fail) return jsonResponse({ detail: 'The search index is rebuilding.' }, 500);
      const q = url.searchParams.get('q') ?? '';
      return jsonResponse(makeResults(q, Number(url.searchParams.get('limit'))));
    },
  });
  const searches = () =>
    fetchMock.mock.calls
      .map(([input]) => new URL(input instanceof Request ? input.url : input.toString()))
      .filter((url) => url.pathname === '/search')
      .map((url) => `${url.searchParams.get('q') ?? ''}|${url.searchParams.get('limit') ?? ''}`);
  return { fetchMock, searches };
}

const box = () => screen.getByRole('searchbox', { name: 'Search jobs' });
const titles = () =>
  within(screen.getByRole('list', { name: 'Results' }))
    .getAllByRole('heading')
    .map((h) => h.textContent);

describe('searching', () => {
  it('keeps the box in the URL as you type, and searches once you pause', async () => {
    const { searches } = setup();
    const { user, router } = renderApp('/search');
    await user.type(await screen.findByRole('searchbox', { name: 'Search jobs' }), 'python');
    expect(router.state.location.search).toBe('?q=python'); // at once, keystroke by keystroke
    expect(await screen.findByText('10 results for “python”')).toBeInTheDocument();
    expect(searches()).toEqual(['python|10']); // one request, not one per letter
    expect(titles()[0]).toBe('python job 1');
  });

  it('loads straight from a shared link', async () => {
    setup();
    renderApp('/search?q=icu%20nurse');
    expect(await screen.findByRole('searchbox', { name: 'Search jobs' })).toHaveValue('icu nurse');
    expect(await screen.findByText('10 results for “icu nurse”')).toBeInTheDocument();
  });

  it('keeps the old results on screen, marked busy, while new ones load', async () => {
    setup({ delay: 150 });
    const { user } = renderApp('/search?q=python');
    await screen.findByText('10 results for “python”');
    await user.type(box(), ' remote');
    expect(screen.getByRole('list', { name: 'Results' })).toHaveAttribute('aria-busy', 'true');
    expect(titles()[0]).toBe('python job 1'); // no skeleton flash
    await waitFor(() => {
      expect(titles()[0]).toBe('python remote job 1');
    });
    expect(screen.getByRole('list', { name: 'Results' })).toHaveAttribute('aria-busy', 'false');
  });

  it('shows 10 more on request, keeping the size in the URL', async () => {
    const { searches } = setup();
    const { user, router } = renderApp('/search?q=python');
    await screen.findByText('10 results for “python”');
    await user.click(screen.getByRole('button', { name: 'Show 10 more' }));
    expect(await screen.findByText('20 results for “python”')).toBeInTheDocument();
    expect(router.state.location.search).toBe('?q=python&limit=20');
    expect(searches()).toEqual(['python|10', 'python|20']);
  });

  it('opens a result in the details drawer, and Back closes it with the search intact', async () => {
    setup();
    const { user, router } = renderApp('/search?q=python');
    await screen.findByText('10 results for “python”');
    await user.click(screen.getByRole('link', { name: 'python job 1' }));
    expect(await screen.findByRole('dialog', { name: 'python job 1' })).toBeInTheDocument();
    await router.navigate(-1);
    await waitFor(() => {
      expect(router.state.location.search).toBe('?q=python');
    });
    expect(box()).toHaveValue('python');
  });
});

describe('states', () => {
  it('suggests searches when empty, and asks for 2 characters before searching', async () => {
    const { searches } = setup();
    const { user } = renderApp('/search');
    expect(await screen.findByRole('link', { name: 'not sales' })).toHaveAttribute(
      'href',
      '/search?q=not%20sales',
    );
    await user.type(box(), 'a');
    expect(screen.getByText('Type at least 2 characters.')).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(searches()).toEqual([]);
  });

  it('shows the error and can retry', async () => {
    setup({ fail: true });
    renderApp('/search?q=python');
    expect(await screen.findByRole('alert')).toHaveTextContent('The search index is rebuilding.');
  });

  it('has no problems axe can find', async () => {
    setup();
    renderApp('/search?q=python');
    await screen.findByText('10 results for “python”');
    expect(await axeViolations()).toEqual([]);
  });
});

describe('readLimit', () => {
  it.each([
    [null, 10],
    ['20', 20],
    ['50', 50],
    ['25', 20],
    ['60', 10],
    ['abc', 10],
    ['-10', 10],
  ])('%s → %s', (value, expected) => {
    expect(readLimit(value)).toBe(expected);
  });
});
