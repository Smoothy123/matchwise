import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getProfileId,
  newProfileId,
  resetProfileIdCache,
  STORAGE_KEY,
  startFresh,
  subscribe,
} from './profileId';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

beforeEach(() => {
  resetProfileIdCache();
});

describe('the profile id', () => {
  it('is created once, saved, and read back after a reload', () => {
    const id = getProfileId();
    expect(id).toMatch(UUID_V4);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(id);
    resetProfileIdCache(); // as if the page reloaded
    expect(getProfileId()).toBe(id);
  });

  it('replaces a stored value the API would reject', () => {
    localStorage.setItem(STORAGE_KEY, 'has spaces/and slashes');
    expect(getProfileId()).toMatch(UUID_V4);
  });

  it('still works when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    const id = getProfileId();
    expect(id).toMatch(UUID_V4);
    expect(getProfileId()).toBe(id); // stable for the life of the page
  });

  it('is replaced by "start fresh", and subscribers hear about it', () => {
    const before = getProfileId();
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);
    const after = startFresh();
    unsubscribe();
    expect(after).not.toBe(before);
    expect(getProfileId()).toBe(after);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(after);
    expect(listener).toHaveBeenCalledOnce();
  });

  it('follows a change made in another tab', () => {
    getProfileId();
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);
    localStorage.setItem(STORAGE_KEY, 'from-another-tab');
    window.dispatchEvent(new StorageEvent('storage', { key: STORAGE_KEY }));
    unsubscribe();
    expect(listener).toHaveBeenCalledOnce();
    expect(getProfileId()).toBe('from-another-tab');
  });
});

describe('newProfileId', () => {
  it('makes a valid UUID even where crypto.randomUUID is missing (plain http)', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
    const ids = new Set(Array.from({ length: 50 }, newProfileId));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(UUID_V4);
  });
});
