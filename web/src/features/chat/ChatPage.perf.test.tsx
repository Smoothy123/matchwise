/**
 * Typing in the composer with a long conversation. The chat page re-renders on every keystroke
 * (the draft is its state); past turns must not, or typing gets slow as the conversation grows.
 *
 * Measured with React's <Profiler>, 150 turns, 40 keystrokes (median render per keystroke):
 * 11.3 ms before TurnView was memoised, 0.28 ms after. Run `npm test -- --silent=false ChatPage.perf`
 * to see the current numbers; the timing test only prints them (machines differ), the other one
 * fails if past turns start re-rendering again.
 */
import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { Profiler } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';

import { createQueryClient } from '../../api/queries';
import { jsonResponse, mockApi } from '../../test/fetch';
import { chatRows as row, HEALTHY } from '../../test/fixtures';
import { resetProfileIdCache, STORAGE_KEY } from '../profile/profileId';
import ChatPage from './ChatPage';
import { ReplyText } from './ReplyText';

// Counts renders of each reply, while still rendering it for real.
vi.mock('./ReplyText', async (importOriginal) => {
  const original = await importOriginal<typeof import('./ReplyText')>();
  return { ...original, ReplyText: vi.fn(original.ReplyText) };
});

const TURNS = 150;
const KEYSTROKES = 40;

function longConversation() {
  return Array.from({ length: TURNS }, (_, i) => [
    row.user(i + 1, `Message ${String(i)}: data analyst roles in Chicago, remote is fine.`),
    row.toolRequest(i + 1, [[`c${String(i)}`, 'search_jobs', { query: 'data analyst' }]]),
    row.toolResult(i + 1, `c${String(i)}`, { result: [] }),
    row.reply(
      i + 1,
      `Here are some:\n* **Data Analyst** at Acme [#${String(1000 + i)}]\n* BI Developer at Beta [#${String(2000 + i)}]\nWant more?`,
    ),
  ]).flat();
}

async function renderChat(onRender?: (duration: number) => void) {
  const router = createMemoryRouter([
    {
      path: '/',
      element: (
        <Profiler
          id="chat"
          onRender={(_id, phase, duration) => {
            if (phase === 'update') onRender?.(duration);
          }}
        >
          <ChatPage />
        </Profiler>
      ),
    },
  ]);
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByText(
    `Message ${String(TURNS - 1)}: data analyst roles in Chicago, remote is fine.`,
  );
  return screen.getByRole('textbox', { name: 'Message' });
}

function type(box: HTMLElement) {
  let text = '';
  for (let i = 0; i < KEYSTROKES; i += 1) {
    text += 'a';
    fireEvent.change(box, { target: { value: text } });
  }
}

beforeEach(() => {
  localStorage.setItem(STORAGE_KEY, 'p1');
  resetProfileIdCache();
  mockApi({
    'GET /health': HEALTHY,
    'GET /profiles/p1/chat': () => jsonResponse(longConversation()),
  });
});

it("doesn't re-render past turns while you type", async () => {
  const box = await renderChat();
  vi.mocked(ReplyText).mockClear();
  type(box);
  expect(box).toHaveValue('a'.repeat(KEYSTROKES));
  expect(vi.mocked(ReplyText)).not.toHaveBeenCalled(); // without memo: 150 × 40 = 6,000 renders
});

it('measures render time per keystroke (printed, not asserted)', async () => {
  const durations: number[] = [];
  const box = await renderChat((duration) => durations.push(duration));
  durations.length = 0;
  type(box);
  const sorted = [...durations].sort((a, b) => a - b);
  const at = (q: number) => (sorted[Math.floor(sorted.length * q)] ?? 0).toFixed(2);
  console.log(
    `PROFILE ${String(TURNS)} turns: median ${at(0.5)} ms, p95 ${at(0.95)} ms per keystroke`,
  );
  expect(durations).toHaveLength(KEYSTROKES);
});
