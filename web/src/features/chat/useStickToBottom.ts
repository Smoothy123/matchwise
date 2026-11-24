import { useCallback, useEffect, useRef, useState } from 'react';

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Keeps the newest message in view, unless the person has scrolled up to read something.
 *
 * An IntersectionObserver watches an empty element after the last message. While it's on screen
 * (or within NEAR_PX of it), the person is "at the bottom" and new content scrolls into view.
 * Once they scroll up, new content leaves the page alone and `hasUnseen` offers a "jump to the
 * latest" button instead. No scroll listeners, so nothing runs on every scroll event.
 */
const NEAR_PX = 120;

export function useStickToBottom(contentKey: unknown) {
  const endRef = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const firstScroll = useRef(true);
  const [hasUnseen, setHasUnseen] = useState(false);

  useEffect(() => {
    const end = endRef.current;
    if (!end) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        atBottom.current = entry?.isIntersecting ?? true;
        if (atBottom.current) setHasUnseen(false);
      },
      { rootMargin: `0px 0px ${String(NEAR_PX)}px 0px` },
    );
    observer.observe(end);
    return () => {
      observer.disconnect();
    };
  }, []);

  const scrollToEnd = useCallback((smooth: boolean) => {
    // The page scrolls, not an inner box: the composer is sticky at the bottom of the window,
    // so the very bottom of the page is where the newest message sits just above it.
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: smooth && !prefersReducedMotion() ? 'smooth' : 'auto',
    });
    setHasUnseen(false);
  }, []);

  useEffect(() => {
    if (contentKey === undefined) return; // nothing loaded yet
    if (firstScroll.current) {
      firstScroll.current = false;
      scrollToEnd(false); // opening the page: start at the latest message, no animation
    } else if (atBottom.current) {
      scrollToEnd(true);
    } else {
      setHasUnseen(true);
    }
  }, [contentKey, scrollToEnd]);

  return {
    endRef,
    hasUnseen,
    jumpToLatest: () => {
      scrollToEnd(true);
    },
  };
}
