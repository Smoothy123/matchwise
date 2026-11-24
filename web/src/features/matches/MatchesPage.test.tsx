import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { Health, Match } from '../../api/client';
import { axeViolations } from '../../test/axe';
import { jsonResponse, mockApi } from '../../test/fetch';
import { HEALTHY, makeJob, makeMatch, makeProfile, NO_LLM, REASON } from '../../test/fixtures';
import { renderApp } from '../../test/render';
import { resetProfileIdCache, STORAGE_KEY } from '../profile/profileId';
import { parseJobId } from './JobDrawer';

const SECOND = makeMatch({
  job_id: 4001,
  title: 'Registered Nurse Case Manager',
  company: 'W3R Consulting',
  location: 'United States',
  remote: true,
  salary_min: 80_000,
  salary_max: 95_000,
  salary_currency: 'USD',
  score: 0.8,
});
const FIRST = makeMatch();
const EXPLAINED: Match[] = [
  { ...FIRST, explanation: REASON },
  {
    ...SECOND,
    explanation: { reason: 'A remote case manager role.', matched_preferences: [], caveats: [] },
  },
];

interface Setup {
  health?: Health;
  profile?: unknown;
  matches?: unknown;
  explained?: unknown;
}

/** The fake API for profile "p1". Values may be a Response (an error) or JSON. */
function setup({
  health = HEALTHY,
  profile = makeProfile(),
  matches = [FIRST, SECOND],
  explained = EXPLAINED,
}: Setup = {}) {
  return mockApi({
    'GET /health': health,
    'GET /profiles/p1': profile,
    'GET /profiles/p1/matches': (url: URL) => {
      const body = url.searchParams.get('explain') === 'true' ? explained : matches;
      return body instanceof Response ? body.clone() : jsonResponse(body);
    },
    'GET /jobs/5083': makeJob(),
    'GET /jobs/777': makeJob({ id: 777, title: 'Linked From Chat', is_active: false }),
  });
}

function matchRequests(fetchMock: ReturnType<typeof setup>): (string | null)[] {
  return fetchMock.mock.calls
    .map(([input]) => new URL(input instanceof Request ? input.url : input.toString()))
    .filter((url) => url.pathname.endsWith('/matches'))
    .map((url) => url.searchParams.get('explain'));
}

beforeEach(() => {
  localStorage.setItem(STORAGE_KEY, 'p1');
  resetProfileIdCache();
});

describe('loading matches', () => {
  it('shows the ranked list first, then fills in the reasons from a second request', async () => {
    const fetchMock = setup();
    renderApp('/matches');
    expect(
      await screen.findByRole('heading', { name: 'Registered Nurse, Emergency Room' }),
    ).toBeInTheDocument();
    expect(await screen.findByText(REASON.reason)).toBeInTheDocument();
    expect(matchRequests(fetchMock)).toEqual(['false', 'true']); // in that order, never together
    const [first] = within(screen.getByRole('list', { name: 'Matches' })).getAllByRole('article');
    expect(first).toHaveTextContent('#1');
    expect(within(first as HTMLElement).getByRole('img')).toHaveAccessibleName(
      'Score 0.86 of 1: Meaning 0.56, Location 0.23, Recency 0.06',
    );
    expect(first).toHaveTextContent('Hard limits checked');
    expect(screen.getByText(/Ranked for:/).parentElement).toHaveTextContent(
      'Ranked for: registered nurse, Texas. Hard limits: no “night shift”.',
    );
  });

  it('shows a card with two caveats and links to the rest', async () => {
    setup();
    renderApp('/matches');
    await screen.findByText(REASON.reason);
    expect(screen.getByText('Not listed as remote')).toBeInTheDocument();
    expect(screen.queryByText('Benefits not stated')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /1 more in details/ })).toHaveAttribute(
      'href',
      '/matches?job=5083',
    );
  });

  it('warns on a job whose hard limits could not be checked', async () => {
    setup({
      matches: [makeMatch({ limit_check: 'skipped' })],
      explained: [makeMatch({ limit_check: 'skipped' })],
    });
    renderApp('/matches');
    expect(await screen.findByText('Hard limits not fully checked')).toBeInTheDocument();
    expect(screen.getByText(/only the automatic filters ran/)).toBeInTheDocument();
  });

  it('without an LLM, ranks without asking for reasons, and says why', async () => {
    const fetchMock = setup({ health: NO_LLM });
    renderApp('/matches');
    expect(await screen.findByText(/Reasons need the language model/)).toBeInTheDocument();
    await screen.findByRole('heading', { name: 'Registered Nurse, Emergency Room' });
    expect(matchRequests(fetchMock)).toEqual(['false']);
  });

  it('keeps the cards when the reasons fail, and can try again', async () => {
    const fetchMock = setup({ explained: jsonResponse({ detail: 'busy' }, 503) });
    const { user } = renderApp('/matches');
    expect(await screen.findByText(/reasons couldn't be written/)).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(2);

    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(EXPLAINED)));
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText(REASON.reason)).toBeInTheDocument();
  });
});

describe('states', () => {
  it('asks a new person to start in the chat, without requesting matches', async () => {
    const fetchMock = setup({ profile: jsonResponse({ detail: 'No profile' }, 404) });
    renderApp('/matches');
    expect(await screen.findByRole('heading', { name: 'No preferences yet' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Tell the chat/ })).toHaveAttribute('href', '/');
    expect(matchRequests(fetchMock)).toEqual([]);
  });

  it('explains when only hard limits were given (the API answers 422)', async () => {
    setup({ matches: jsonResponse({ detail: "Tell me what you're looking for first." }, 422) });
    renderApp('/matches');
    expect(
      await screen.findByRole('heading', { name: 'Nothing to search for yet' }),
    ).toBeInTheDocument();
  });

  it('says when nothing passes the hard limits', async () => {
    setup({ matches: [], explained: [] });
    renderApp('/matches');
    expect(
      await screen.findByRole('heading', { name: 'No open jobs pass your hard limits' }),
    ).toBeInTheDocument();
  });

  it('shows the error and recovers on retry', async () => {
    const fetchMock = setup({
      matches: jsonResponse({ detail: 'The database is restarting.' }, 500),
    });
    const { user } = renderApp('/matches');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("Couldn't load your matches");
    expect(alert).toHaveTextContent('The database is restarting.');

    fetchMock.mockImplementation((input) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (url.pathname === '/health') return Promise.resolve(jsonResponse(HEALTHY));
      return Promise.resolve(
        jsonResponse(url.searchParams.get('explain') === 'true' ? EXPLAINED : [FIRST]),
      );
    });
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: FIRST.title })).toBeInTheDocument();
  });
});

describe('sorting and filtering', () => {
  it('re-sorts and filters on the client, keeps it in the URL, and can clear it', async () => {
    const fetchMock = setup();
    const { user, router } = renderApp('/matches');
    await screen.findByText(REASON.reason);
    const titles = () => screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(titles()).toEqual([FIRST.title, SECOND.title]);

    await user.selectOptions(screen.getByLabelText('Sort by'), 'Highest pay');
    expect(titles()).toEqual([SECOND.title, FIRST.title]); // pay listed first
    expect(
      within(screen.getAllByRole('article')[0] as HTMLElement).getByText('#2'),
    ).toBeInTheDocument();

    await user.click(screen.getByLabelText('Remote only'));
    expect(titles()).toEqual([SECOND.title]);
    expect(screen.getByText('Showing 1 of 2 matches')).toBeInTheDocument();
    expect(router.state.location.search).toBe('?sort=pay&remote=1');

    await user.type(screen.getByLabelText('Filter'), 'nothing like this');
    expect(
      screen.getByRole('heading', { name: 'No matches fit these filters' }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(titles()).toEqual([SECOND.title, FIRST.title]); // the sort stays
    expect(router.state.location.search).toBe('?sort=pay');
    expect(matchRequests(fetchMock)).toEqual(['false', 'true']); // no new requests: all client-side
  });

  it('opens with the view from a shared URL', async () => {
    setup();
    renderApp('/matches?remote=1');
    await screen.findByText('A remote case manager role.');
    expect(screen.getByLabelText('Remote only')).toBeChecked();
    expect(screen.getAllByRole('article')).toHaveLength(1);
  });
});

describe('the details drawer', () => {
  it('opens from a card, shows the breakdown and the posting, and closes back to the list', async () => {
    setup();
    const { user, router } = renderApp('/matches');
    await screen.findByText(REASON.reason);
    await user.click(screen.getByRole('link', { name: FIRST.title }));

    const dialog = await screen.findByRole('dialog', { name: FIRST.title });
    expect(router.state.location.search).toBe('?job=5083');
    expect(within(dialog).getByRole('button', { name: 'Close details' })).toHaveFocus();
    expect(within(dialog).getByText('Benefits not stated')).toBeInTheDocument(); // every caveat
    const table = within(dialog).getByRole('table', { name: `Score breakdown for ${FIRST.title}` });
    expect(
      within(table)
        .getAllByRole('row')
        .map((row) => row.textContent),
    ).toEqual([
      'PartValueWeightAdds',
      expect.stringMatching(/^Meaning.*0\.810\.690\.56$/),
      expect.stringMatching(/^Location.*1\.000\.230\.23$/),
      expect.stringMatching(/^Recency.*0\.820\.080\.06$/),
      'Score0.86',
    ]);
    expect(await within(dialog).findByText(/BLS and ACLS required/)).toBeInTheDocument();
    expect(await axeViolations(dialog)).toEqual([]);

    await user.click(within(dialog).getByRole('button', { name: 'Close details' }));
    await waitFor(() => {
      expect(router.state.location.search).toBe('');
    });
    expect(dialog).not.toHaveAttribute('open');
  });

  it('opens from a link to a job outside the matches, and says when it has closed', async () => {
    setup();
    const { user, router } = renderApp('/matches?job=777');
    const dialog = await screen.findByRole('dialog', { name: 'Linked From Chat' });
    expect(within(dialog).getByText(/no longer open/)).toBeInTheDocument();
    expect(within(dialog).queryByText('Score breakdown')).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Close details' }));
    await waitFor(() => {
      expect(router.state.location.search).toBe('');
    });
  });
});

describe('accessibility', () => {
  it('has no problems axe can find on the loaded list', async () => {
    setup();
    renderApp('/matches');
    await screen.findByText(REASON.reason);
    expect(await axeViolations()).toEqual([]);
  });
});

describe('parseJobId', () => {
  it.each([
    ['5083', 5083],
    [null, null],
    ['', null],
    ['abc', null],
    ['0', null],
    ['-4', null],
    ['1.5', null],
    ['9999999999999999', null], // past what a JavaScript number holds exactly
  ])('%s → %s', (value, expected) => {
    expect(parseJobId(value)).toBe(expected);
  });
});
