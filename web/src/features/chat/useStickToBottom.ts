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
  // False until the first scroll to the end: the conversation stays hidden until then.
  const [positioned, setPositioned] = useState(false);

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
      // Opening the page: start at the latest message. Not in this frame, though: scrolling in
      // the same frame as the history appearing counted as a large layout shift (Lighthouse
      // measured CLS 0.69), because the footer and the conversation moved and came into view at
      // once. So the history is laid out hidden for one painted frame (nothing visible moves),
      // then the next frame jumps to the end and reveals it: loading state, then the latest
      // message, with no glimpse of the top in between.
      let inner = 0;
      const outer = requestAnimationFrame(() => {
        inner = requestAnimationFrame(() => {
          scrollToEnd(false);
          setPositioned(true);
        });
      });
      return () => {
        cancelAnimationFrame(outer);
        cancelAnimationFrame(inner);
      };
    } else if (atBottom.current) {
      scrollToEnd(true);
    } else {
      setHasUnseen(true);
    }
    return undefined;
  }, [contentKey, scrollToEnd]);

  return {
    endRef,
    positioned,
    hasUnseen,
    jumpToLatest: () => {
      scrollToEnd(true);
    },
  };
}
