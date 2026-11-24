import { useEffect, useState } from 'react';

/**
 * `value`, but only once it has stopped changing for `delayMs`. While someone types "python", the
 * search runs once for "python" instead of six times for "p", "py", "pyt"… Each new value
 * cancels the pending timer, so only the last one survives.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delayMs);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delayMs]);
  return debounced;
}
