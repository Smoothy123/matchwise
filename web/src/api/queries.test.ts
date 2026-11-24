import { describe, expect, it } from 'vitest';

import { ApiError } from './client';
import { shouldRetry } from './queries';

describe('shouldRetry', () => {
  it.each([
    ['a network failure', new ApiError('down', 'network'), true],
    ['a timeout', new ApiError('slow', 'timeout'), true],
    ['a busy LLM (503)', new ApiError('busy', 'http', 503), true],
    ['invalid LLM output (502)', new ApiError('bad', 'http', 502), true],
    ['a missing profile (404)', new ApiError('none', 'http', 404), false],
    ['invalid input (422)', new ApiError('bad input', 'http', 422), false],
    ['a bug in our own code', new TypeError('x is undefined'), false],
  ])('after %s: %s', (_name, error, expected) => {
    expect(shouldRetry(0, error)).toBe(expected);
  });

  it('gives up after two retries', () => {
    const error = new ApiError('down', 'network');
    expect([0, 1, 2].map((count) => shouldRetry(count, error))).toEqual([true, true, false]);
  });
});
