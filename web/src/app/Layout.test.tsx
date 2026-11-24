import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Health } from '../api/client';
import { getProfileId, resetProfileIdCache, STORAGE_KEY } from '../features/profile/profileId';
import { axeViolations } from '../test/axe';
import { jsonResponse, mockApi } from '../test/fetch';
import { renderApp } from '../test/render';

const HEALTHY: Health = {
  status: 'ok',
  jobs: 5450,
  active_jobs: 5000,
  embedded_jobs: 5000,
  llm_configured: true,
};

describe('the layout', () => {
  it('has a skip link, a labelled nav with the current page marked, and the page heading', async () => {
    mockApi({ 'GET /health': HEALTHY });
    renderApp('/');
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((link) => link.textContent)).toEqual([
      'Chat',
      'Matches',
      'Preferences',
      'Search',
      'Evals',
    ]);
    expect(within(nav).getByRole('link', { name: 'Chat' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByRole('heading', { level: 1, name: 'Chat' })).toBeInTheDocument();
  });

  it('moves focus to the new page after navigating, and updates the title', async () => {
    mockApi({ 'GET /health': HEALTHY });
    const { user } = renderApp('/');
    await screen.findByRole('heading', { level: 1, name: 'Chat' });
    await user.click(screen.getByRole('link', { name: 'Matches' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Matches' })).toBeInTheDocument();
    expect(screen.getByRole('main')).toHaveFocus();
    expect(document.title).toBe('Matches · Matchwise');
  });

  it('shows a not-found page inside the layout', async () => {
    mockApi({ 'GET /health': HEALTHY });
    renderApp('/no-such-page');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });

  it('has no accessibility problems axe can find', async () => {
    mockApi({ 'GET /health': HEALTHY });
    renderApp('/');
    await screen.findByText('API online · LLM on');
    await screen.findByRole('heading', { level: 1, name: 'Chat' });
    expect(await axeViolations()).toEqual([]);
  });
});

describe('API status', () => {
  it('says when the API and its LLM are up, with no banner', async () => {
    mockApi({ 'GET /health': HEALTHY });
    renderApp();
    expect(screen.getByText('Checking API…')).toBeInTheDocument();
    expect(await screen.findByText('API online · LLM on')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Connection status' })).toBeEmptyDOMElement();
  });

  it('explains what still works when the LLM is off', async () => {
    mockApi({ 'GET /health': { ...HEALTHY, llm_configured: false } });
    renderApp();
    expect(await screen.findByText('API online · LLM off')).toBeInTheDocument();
    expect(screen.getByText(/Search and matching still work/)).toBeInTheDocument();
  });

  it('says when the API is unreachable, and recovers on Retry', async () => {
    const fetchMock = mockApi({
      'GET /health': () => Promise.reject(new TypeError('Failed to fetch')),
    });
    const { user } = renderApp();
    expect(await screen.findByText('API offline')).toBeInTheDocument();
    expect(screen.getByText(/Can't reach the Matchwise API/)).toBeInTheDocument();

    fetchMock.mockResolvedValue(jsonResponse(HEALTHY));
    await user.click(screen.getByRole('button', { name: 'Retry connecting to the API' }));
    expect(await screen.findByText('API online · LLM on')).toBeInTheDocument();
    expect(screen.queryByText(/Can't reach the Matchwise API/)).not.toBeInTheDocument();
  });

  it('says when the browser is offline', async () => {
    mockApi({ 'GET /health': HEALTHY });
    renderApp();
    await screen.findByText('API online · LLM on');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    window.dispatchEvent(new Event('offline'));
    expect(await screen.findByText(/You're offline. Matchwise will carry on/)).toBeInTheDocument();
  });
});

describe('start fresh', () => {
  it('asks first, and Cancel keeps the profile', async () => {
    mockApi({ 'GET /health': HEALTHY });
    resetProfileIdCache();
    const before = getProfileId();
    const { user } = renderApp();
    await user.click(screen.getByRole('button', { name: 'Start fresh' }));
    const dialog = screen.getByRole('dialog', { name: 'Start a fresh profile?' });
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(dialog).not.toHaveAttribute('open');
    expect(localStorage.getItem(STORAGE_KEY)).toBe(before);
  });

  it('switches this browser to a new, empty profile', async () => {
    mockApi({ 'GET /health': HEALTHY });
    resetProfileIdCache();
    const before = getProfileId();
    const { user } = renderApp();
    expect(screen.getByText(before.slice(0, 8))).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start fresh' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Start fresh' }));
    await waitFor(() => {
      expect(localStorage.getItem(STORAGE_KEY)).not.toBe(before);
    });
    const after = localStorage.getItem(STORAGE_KEY) ?? '';
    expect(screen.getByText(after.slice(0, 8))).toBeInTheDocument();
  });
});
