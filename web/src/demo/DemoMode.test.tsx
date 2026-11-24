import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { axeViolations } from '../test/axe';
import { renderApp } from '../test/render';
import checked from './recorded/matches-checked.json';

// The demo must never call a server: any fetch fails the test.
const fetchSpy = vi.fn(() => Promise.reject(new Error('The demo called the network')));

beforeEach(() => {
  vi.stubEnv('VITE_DEMO_MODE', 'true');
  vi.stubGlobal('fetch', fetchSpy);
  fetchSpy.mockClear();
});

describe('demo mode', () => {
  it('says on every page that the data is recorded, not live', async () => {
    const { user } = renderApp('/matches');
    expect(await screen.findByText('Demo · recorded data')).toBeInTheDocument();
    expect(screen.getByText(/recorded from the real Matchwise API/)).toHaveTextContent(
      'Nothing is live',
    );
    await user.click(screen.getByRole('link', { name: 'Evals' }));
    expect(screen.getByText(/recorded from the real Matchwise API/)).toBeInTheDocument();
  });

  it('shows the recorded matches without any network request', async () => {
    renderApp('/matches');
    await waitFor(() => {
      expect(screen.getAllByRole('article')).toHaveLength(checked.length);
    });
    expect(
      within(screen.getAllByRole('article')[0] as HTMLElement).getByRole('heading'),
    ).toHaveTextContent(checked[0]?.title ?? '');
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(await axeViolations()).toEqual([]);
  });

  it('shows the recorded conversation and explains why it can’t send', async () => {
    renderApp('/');
    expect(
      await screen.findByText(/conversation was recorded, so new messages can’t be sent/),
    ).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear conversation' })).toBeDisabled();
    expect(screen.getByText('Demo profile: one recorded conversation')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start fresh' })).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
