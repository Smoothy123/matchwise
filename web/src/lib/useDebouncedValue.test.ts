import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDebouncedValue } from './useDebouncedValue';

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('useDebouncedValue', () => {
  it('passes a value on only after it has stopped changing for the delay', () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: 'p' },
    });
    expect(result.current).toBe('p'); // the first value is used at once (a shared link loads)

    rerender({ value: 'py' });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender({ value: 'pyt' }); // typing again restarts the wait
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current).toBe('p');

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(result.current).toBe('pyt');
  });
});
