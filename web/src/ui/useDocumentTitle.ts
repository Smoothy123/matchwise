import { useEffect } from 'react';

/** Each page sets the tab title; screen readers also announce it after a navigation. */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · Matchwise`;
  }, [title]);
}
