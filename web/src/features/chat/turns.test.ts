import { describe, expect, it } from 'vitest';

import { chatRows as row } from '../../test/fixtures';
import {
  describeArguments,
  groupTurns,
  preferencesNotSaved,
  toolSucceeded,
  type Turn,
} from './turns';

describe('groupTurns', () => {
  it('folds the stored rows into turns: message, tools (and whether each worked), reply', () => {
    const turns = groupTurns([
      row.user(1, 'Nurse in Texas, no nights.'),
      row.toolRequest(1, [['c1', 'update_preferences', { message: 'Nurse in Texas, no nights.' }]]),
      row.toolResult(1, 'c1', { result: { changes: ['add wants.roles'] } }),
      row.toolRequest(1, [
        ['c2', 'get_matches', {}],
        ['c3', 'explain_match', { job_id: 1 }],
      ]),
      row.toolResult(1, 'c3', { error: 'No open job with id 1.' }), // results can arrive in any order
      row.toolResult(1, 'c2', { result: [] }),
      row.reply(1, 'Saved. Nothing fits yet.'),
      row.user(2, 'Thanks!'),
      row.reply(2, "You're welcome."),
    ]);
    expect(turns).toEqual([
      {
        turn: 1,
        message: 'Nurse in Texas, no nights.',
        reply: 'Saved. Nothing fits yet.',
        tools: [
          {
            name: 'update_preferences',
            arguments: '{"message":"Nurse in Texas, no nights."}',
            ok: true,
          },
          { name: 'get_matches', arguments: '{}', ok: true },
          { name: 'explain_match', arguments: '{"job_id":1}', ok: false },
        ],
      },
      { turn: 2, message: 'Thanks!', reply: "You're welcome.", tools: [] },
    ]);
  });

  it('is empty for an empty conversation', () => {
    expect(groupTurns([])).toEqual([]);
  });
});

describe('toolSucceeded', () => {
  it('follows the API: a result is fine, an "error" key is a failure', () => {
    expect(toolSucceeded('{"result": 1}')).toBe(true);
    expect(toolSucceeded('{"error": "no"}')).toBe(false);
    expect(toolSucceeded('not json')).toBe(true);
    expect(toolSucceeded(null)).toBe(true);
  });
});

describe('describeArguments', () => {
  it('lists arguments as "key: value", and copes with anything else', () => {
    expect(describeArguments('{"query": "nurse", "limit": 5}')).toEqual([
      'query: nurse',
      'limit: 5',
    ]);
    expect(describeArguments('')).toEqual([]);
    expect(describeArguments('[1, 2]')).toEqual(['[1, 2]']);
    expect(describeArguments('{broken')).toEqual(['{broken']);
  });
});

describe('preferencesNotSaved', () => {
  const turn = (...results: boolean[]): Turn => ({
    turn: 1,
    message: 'm',
    reply: 'r',
    tools: results.map((ok) => ({ name: 'update_preferences', arguments: '{}', ok })),
  });
  it('is true only when every save in the turn failed', () => {
    expect(preferencesNotSaved(turn(false))).toBe(true);
    expect(preferencesNotSaved(turn(false, true))).toBe(false); // a retry in the same turn worked
    expect(preferencesNotSaved(turn())).toBe(false); // no save attempted
  });
});
