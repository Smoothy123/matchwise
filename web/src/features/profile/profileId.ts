/**
 * One anonymous profile per browser: a random id kept in localStorage. The API has no accounts
 * yet, so this id is the only key to the profile; it's random (122 bits), so it can't be guessed.
 *
 * A tiny external store (subscribe + getSnapshot) so React can read it with useSyncExternalStore,
 * and so "Start fresh" in one tab updates the others through the `storage` event.
 */
import { useSyncExternalStore } from 'react';

export const STORAGE_KEY = 'matchwise.profileId';
const VALID_ID = /^[A-Za-z0-9_-]{1,64}$/; // the API's own rule for profile ids

/** A version 4 UUID. crypto.randomUUID only exists in secure contexts (https or localhost), so
 * opening the dev server from a phone at http://192.168.x.x would break without this fallback. */
export function newProfileId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

let current: string | null = null; // cached, because getSnapshot must return the same value each call
const listeners = new Set<() => void>();

function save(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage blocked (some private modes, strict settings): the id lives for this page only.
  }
}

function load(): string {
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(STORAGE_KEY);
  } catch {
    // as above
  }
  if (stored && VALID_ID.test(stored)) return stored;
  const id = newProfileId();
  save(id);
  return id;
}

export function getProfileId(): string {
  current ??= load();
  return current;
}

function notify(): void {
  for (const listener of listeners) listener();
}

/** "Start fresh": a new, empty profile. The old one stays on the server, unreachable from here. */
export function startFresh(): string {
  current = newProfileId();
  save(current);
  notify();
  return current;
}

function onStorage(event: StorageEvent): void {
  if (event.key !== STORAGE_KEY) return;
  current = null; // another tab changed it: read it again
  notify();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (listeners.size === 1) window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener('storage', onStorage);
  };
}

export function useProfileId(): string {
  return useSyncExternalStore(subscribe, getProfileId);
}

/** For tests: forget the cached id so the next read goes to storage again. */
export function resetProfileIdCache(): void {
  current = null;
}
