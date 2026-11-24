import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { HistoryItem } from '../../api/client';
import { axeViolations } from '../../test/axe';
import { jsonResponse, mockApi } from '../../test/fetch';
import { HEALTHY, makeProfile } from '../../test/fixtures';
import { renderApp } from '../../test/render';
import { resetProfileIdCache, STORAGE_KEY } from '../profile/profileId';

const HISTORY: HistoryItem[] = [
  {
    version: 1,
    content: "I'm a registered nurse. I want to stay in Texas and I won't do night shifts.",
    operations: [
      {
        op: 'add',
        field: 'wants.roles',
        value: 'registered nurse',
        evidence: "I'm a registered nurse.",
      },
      { op: 'add', field: 'wants.locations', value: 'Texas', evidence: 'stay in Texas' },
      {
        op: 'add',
        field: 'dealbreakers.exclude_description_phrases',
        value: 'night shift',
        evidence: "I won't do night shifts.",
      },
    ],
    notes: [],
    model: 'gemini-3.5-flash-lite',
    prompt_version: 'preferences-v2',
    created_at: '2026-11-24T12:11:27Z',
  },
  {
    version: 2,
    content: 'Thanks!',
    operations: [],
    notes: ['Nothing to change.'],
    model: 'gemini-3.5-flash-lite',
    prompt_version: 'preferences-v2',
    created_at: '2026-11-24T12:20:00Z',
  },
];

function setup(profile: unknown = makeProfile(), history: unknown = HISTORY) {
  return mockApi({
    'GET /health': HEALTHY,
    'GET /profiles/p1': profile,
    'GET /profiles/p1/messages': history,
  });
}

beforeEach(() => {
  localStorage.setItem(STORAGE_KEY, 'p1');
  resetProfileIdCache();
});

describe('the preferences page', () => {
  it('shows what you want and your hard limits, leaving out what is not set', async () => {
    setup();
    renderApp('/preferences');
    const wants = await screen.findByRole('region', { name: 'What you want' });
    expect(within(wants).getByText('Roles')).toBeInTheDocument();
    expect(within(wants).getByText('registered nurse')).toBeInTheDocument();
    expect(within(wants).queryByText('Skills')).not.toBeInTheDocument();
    const limits = screen.getByRole('region', { name: 'Hard limits' });
    expect(within(limits).getByText('Phrases ruled out')).toBeInTheDocument();
    expect(within(limits).getByText('night shift')).toBeInTheDocument();
  });

  it('shows how each message changed them, with the words each change came from', async () => {
    setup();
    renderApp('/preferences');
    const first = (await screen.findByText('Version 1')).closest('li') as HTMLElement;
    const changes = within(first).getByRole('list', { name: 'Changes' });
    expect(
      within(changes)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual([
      "+Added “registered nurse” to Roles, from “I'm a registered nurse.”",
      '+Added “Texas” to Places, from “stay in Texas”',
      "+Added “night shift” to Phrases ruled out, from “I won't do night shifts.”",
    ]);
    expect(
      within(first).getByText(/Read by gemini-3.5-flash-lite with prompt preferences-v2/),
    ).toBeInTheDocument();

    const second = screen.getByText('Version 2').closest('li') as HTMLElement;
    expect(within(second).getByText(/No changes/)).toBeInTheDocument();
    expect(within(second).getByText('Nothing to change.')).toBeInTheDocument();
  });

  it('sends a new person to the chat', async () => {
    setup(jsonResponse({ detail: 'No profile' }, 404), jsonResponse({ detail: 'No profile' }, 404));
    renderApp('/preferences');
    expect(await screen.findByRole('heading', { name: 'Nothing saved yet' })).toBeInTheDocument();
  });

  it('still shows the preferences when only the history fails, with a retry', async () => {
    setup(makeProfile(), jsonResponse({ detail: 'Database busy' }, 500));
    renderApp('/preferences');
    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load the history");
    expect(screen.getByText('registered nurse')).toBeInTheDocument();
  });

  it('has no problems axe can find', async () => {
    setup();
    renderApp('/preferences');
    await screen.findByText('Version 2');
    expect(await axeViolations()).toEqual([]);
  });
});
