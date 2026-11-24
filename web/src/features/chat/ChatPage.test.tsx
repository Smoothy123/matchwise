import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import type { ChatMessage, ChatReply, Health } from '../../api/client';
import { axeViolations } from '../../test/axe';
import { scrollToMock, viewport } from '../../test/browser';
import { jsonResponse, mockApi } from '../../test/fetch';
import { chatRows as row, HEALTHY, makeProfile, NO_LLM } from '../../test/fixtures';
import { renderApp } from '../../test/render';
import { resetProfileIdCache, STORAGE_KEY } from '../profile/profileId';

const FIRST_TURN = [
  row.user(1, 'Nurse in Texas, no nights.'),
  row.toolRequest(1, [['c1', 'update_preferences', { message: 'Nurse in Texas, no nights.' }]]),
  row.toolResult(1, 'c1', { result: { changes: ['add wants.roles'] } }),
  row.reply(1, 'Saved! Two fit:\n* Nurse at Methodist [#5083]\n* Case Manager [#4001]'),
];

/** A promise the test resolves when it chooses: a reply that is "still being written". */
function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

interface Setup {
  health?: Health;
  history?: ChatMessage[];
  /** How the API answers POST /chat; by default it saves the turn and replies "Done.". */
  answer?: (message: string) => Response | Promise<Response>;
}

/** A fake API that stores turns like the real one: POST appends rows that GET then returns. */
function setup({ health = HEALTHY, history = [], answer }: Setup = {}) {
  const rows = [...history];
  const save = (message: string, reply: ChatReply) => {
    const turn = (rows.at(-1)?.turn ?? 0) + 1;
    rows.push(row.user(turn, message), row.reply(turn, reply.reply));
  };
  const fetchMock = mockApi({
    'GET /health': health,
    'GET /profiles/p1': makeProfile(),
    'GET /profiles/p1/chat': () => jsonResponse(rows),
    'POST /profiles/p1/chat': (_url: URL, init?: RequestInit) => {
      const body = typeof init?.body === 'string' ? init.body : '{}';
      const { message } = JSON.parse(body) as { message: string };
      if (answer) return answer(message);
      const reply: ChatReply = { reply: 'Done.', tool_calls: [] };
      save(message, reply);
      return jsonResponse(reply);
    },
    'DELETE /profiles/p1/chat': () => {
      const deleted = rows.length;
      rows.length = 0;
      return jsonResponse({ deleted_messages: deleted });
    },
  });
  const calls = (method: string, path: string) =>
    fetchMock.mock.calls.filter(([input, init]) => {
      const url = new URL(input instanceof Request ? input.url : input.toString());
      return (init?.method ?? 'GET') === method && url.pathname === path;
    }).length;
  return { fetchMock, rows, save, calls };
}

const input = () => screen.getByRole('textbox', { name: 'Message' });
/** The chat page is lazy-loaded: wait for it before the first keystroke. */
const findInput = () => screen.findByRole('textbox', { name: 'Message' });

beforeEach(() => {
  localStorage.setItem(STORAGE_KEY, 'p1');
  resetProfileIdCache();
});

describe('the conversation', () => {
  it('shows past turns with their replies and a collapsed "tools used" line', async () => {
    setup({ history: FIRST_TURN });
    renderApp('/');
    const log = await screen.findByRole('log', { name: 'Messages' });
    expect(within(log).getByText('Nurse in Texas, no nights.')).toBeInTheDocument();
    expect(within(log).getByRole('link', { name: 'Details for job #4001' })).toBeInTheDocument();
    const tools = within(log).getByText('Used 1 tool: update_preferences').closest('details');
    expect(tools).not.toHaveAttribute('open');
    expect(within(tools as HTMLElement).getByText('Saved your preferences')).toBeInTheDocument();
    expect(scrollToMock).toHaveBeenCalledWith({
      top: expect.any(Number) as number,
      behavior: 'auto',
    });
  });

  it('offers example messages when empty; picking one fills the box without sending', async () => {
    const { calls } = setup();
    const { user } = renderApp('/');
    await user.click(await screen.findByRole('button', { name: /registered nurse/ }));
    expect(input()).toHaveValue(
      "I'm a registered nurse and want to stay in Texas. No night shifts.",
    );
    expect(input()).toHaveFocus();
    expect(calls('POST', '/profiles/p1/chat')).toBe(0);
  });

  it('opens a job mentioned in a reply in the details drawer, over the chat', async () => {
    setup({ history: FIRST_TURN });
    const { user, router } = renderApp('/');
    await user.click(await screen.findByRole('link', { name: 'Details for job #4001' }));
    expect(router.state.location.search).toBe('?job=4001');
    expect(screen.getByRole('log')).toBeInTheDocument();
  });
});

describe('sending', () => {
  it('shows the message at once, waits for the reply, then shows it from the saved history', async () => {
    const reply = deferred<Response>();
    const api = setup({ answer: () => reply.promise });
    const { user } = renderApp('/');
    await user.type(await findInput(), 'Backend roles, remote.{Enter}');

    const log = screen.getByRole('log');
    expect(within(log).getByText('Backend roles, remote.')).toBeInTheDocument();
    expect(within(log).getByText(/Matchwise is working on it/)).toBeInTheDocument();
    expect(input()).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(screen.getByText('Waiting for the reply…')).toBeInTheDocument();

    api.save('Backend roles, remote.', { reply: 'Noted: remote backend roles.', tool_calls: [] });
    reply.resolve(jsonResponse({ reply: 'Noted: remote backend roles.', tool_calls: [] }));
    expect(await within(log).findByText('Noted: remote backend roles.')).toBeInTheDocument();
    expect(within(log).queryByText(/working on it/)).not.toBeInTheDocument();
    expect(within(log).getAllByText('Backend roles, remote.')).toHaveLength(1); // never twice
  });

  it('refreshes the preferences (and so the matches) only when the agent saved some', async () => {
    let toolCalls: ChatReply['tool_calls'] = [];
    const api = setup({
      answer: (message) => {
        const reply = { reply: 'OK.', tool_calls: toolCalls };
        api.save(message, reply);
        return jsonResponse(reply);
      },
    });
    const { user } = renderApp('/matches'); // a page that reads the profile
    await waitFor(() => {
      expect(api.calls('GET', '/profiles/p1')).toBe(1);
    });
    const goTo = async (page: string) => {
      await user.click(screen.getByRole('link', { name: page }));
      await screen.findByRole('heading', { level: 1, name: page });
    };

    await goTo('Chat');
    await user.type(input(), 'Hello{Enter}');
    await screen.findByText('OK.');
    await goTo('Matches');
    expect(api.calls('GET', '/profiles/p1')).toBe(1); // nothing changed: the cached profile is used

    await goTo('Chat');
    toolCalls = [{ name: 'update_preferences', arguments: '{}', ok: true }];
    await user.type(input(), 'Only remote{Enter}');
    await waitFor(() => {
      expect(screen.getAllByText('OK.')).toHaveLength(2);
    });
    await goTo('Matches');
    await waitFor(() => {
      expect(api.calls('GET', '/profiles/p1')).toBe(2); // marked stale, so Matches fetches it again
    });
  });

  it('keeps showing a message that is still waiting after leaving the page and coming back', async () => {
    const reply = deferred<Response>();
    setup({ answer: () => reply.promise });
    const { user } = renderApp('/');
    await user.type(await findInput(), 'Still there?{Enter}');
    await user.click(screen.getByRole('link', { name: 'Search' }));
    await user.click(screen.getByRole('link', { name: 'Chat' }));
    expect(await screen.findByText('Still there?')).toBeInTheDocument();
    expect(screen.getByText(/Matchwise is working on it/)).toBeInTheDocument();
    reply.resolve(jsonResponse({ reply: 'Yes.', tool_calls: [] }));
  });
});

describe('the keyboard', () => {
  it('Shift+Enter starts a new line; Enter while an input method is composing does not send', async () => {
    const { calls } = setup();
    const { user } = renderApp('/');
    await user.type(await findInput(), 'Line one{Shift>}{Enter}{/Shift}Line two');
    expect(input()).toHaveValue('Line one\nLine two');
    fireEvent.keyDown(input(), { key: 'Enter', isComposing: true });
    expect(calls('POST', '/profiles/p1/chat')).toBe(0);
  });

  it('will not send an empty or blank message', async () => {
    const { calls } = setup();
    const { user } = renderApp('/');
    await screen.findByRole('log');
    await user.type(input(), '   {Enter}');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(calls('POST', '/profiles/p1/chat')).toBe(0);
  });
});

describe('failures', () => {
  it('keeps the message, explains, and can send it again or put it back in the box', async () => {
    let attempts = 0;
    const api = setup({
      answer: (message) => {
        attempts += 1;
        if (attempts === 1) {
          return jsonResponse({ detail: 'The language model is unavailable right now.' }, 503);
        }
        const reply = { reply: 'Got it.', tool_calls: [] };
        api.save(message, reply);
        return jsonResponse(reply);
      },
    });
    const { user } = renderApp('/');
    await user.type(
      await screen.findByRole('textbox', { name: 'Message' }),
      'Data analyst roles{Enter}',
    );
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Not answered. The language model is unavailable right now.');

    await user.click(within(alert).getByRole('button', { name: 'Edit message' }));
    expect(input()).toHaveValue('Data analyst roles');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await user.type(input(), '{Enter}');
    expect(await screen.findByText('Got it.')).toBeInTheDocument();
  });

  it("doesn't call it a failure when the reply was saved after all (e.g. the request timed out)", async () => {
    const api = setup({
      answer: (message) => {
        api.save(message, { reply: 'Late but saved.', tool_calls: [] }); // the server finished...
        return Promise.reject(new TypeError('Failed to fetch')); // ...but the answer was lost
      },
    });
    const { user } = renderApp('/');
    await user.type(await findInput(), 'Slow one{Enter}');
    expect(await screen.findByText('Late but saved.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it("says when the agent's attempt to save preferences failed, whatever the reply claims", async () => {
    setup({
      history: [
        row.user(1, 'Save that, please.'),
        row.toolRequest(1, [['c1', 'update_preferences', { message: 'Save that, please.' }]]),
        row.toolResult(1, 'c1', { error: 'InternalServerError: Error code: 503' }),
        row.reply(1, 'I had a bit of trouble saving those, but I have them noted!'),
      ],
    });
    renderApp('/');
    expect(await screen.findByText('Preferences not saved')).toBeInTheDocument();
    expect(screen.getByText(/1 failed/)).toBeInTheDocument();
  });

  it('without an LLM, explains and disables the box', async () => {
    setup({ health: NO_LLM, history: FIRST_TURN });
    renderApp('/');
    expect(await screen.findByText(/isn't configured on this server/)).toBeInTheDocument();
    await waitFor(() => {
      expect(input()).toBeDisabled();
    });
    expect(screen.getByText('Saved! Two fit:')).toBeInTheDocument(); // the history still shows
  });
});

describe('clearing', () => {
  it('asks first, then deletes the messages', async () => {
    setup({ history: FIRST_TURN });
    const { user } = renderApp('/');
    await screen.findByText('Nurse in Texas, no nights.');
    await user.click(screen.getByRole('button', { name: 'Clear conversation' }));
    const dialog = screen.getByRole('dialog', { name: 'Clear this conversation?' });
    await user.click(within(dialog).getByRole('button', { name: 'Clear conversation' }));
    expect(await screen.findByText(/Start with what you're looking for/)).toBeInTheDocument();
    expect(screen.queryByText('Nurse in Texas, no nights.')).not.toBeInTheDocument();
  });
});

describe('scrolling', () => {
  it('follows new messages at the bottom, but not after the person scrolls up', async () => {
    const api = setup({ history: FIRST_TURN });
    const { user } = renderApp('/');
    await screen.findByText('Nurse in Texas, no nights.');
    const scrollTo = scrollToMock;

    scrollTo.mockClear();
    await user.type(input(), 'One{Enter}');
    await screen.findByText('Done.');
    expect(scrollTo).toHaveBeenCalled(); // at the bottom: follows

    viewport.setAtBottom(false); // the person scrolls up to reread something
    scrollTo.mockClear();
    api.save('Two', { reply: 'Second reply.', tool_calls: [] });
    await user.type(input(), 'Three{Enter}');
    const jump = await screen.findByRole('button', { name: /New message/ });
    expect(scrollTo).not.toHaveBeenCalled();

    await user.click(jump);
    expect(scrollTo).toHaveBeenCalledWith({
      top: expect.any(Number) as number,
      behavior: 'smooth',
    });
  });
});

describe('accessibility', () => {
  it('has no problems axe can find', async () => {
    setup({ history: FIRST_TURN });
    renderApp('/');
    await screen.findByText('Nurse in Texas, no nights.');
    expect(await axeViolations()).toEqual([]);
  });
});
