import { useEffect, useRef, useState } from 'react';

/**
 * The element's current width in pixels (0 until measured), kept up to date by a ResizeObserver.
 * Charts draw at their real width rather than scaling a fixed-size SVG, so text stays its
 * normal size on a phone instead of shrinking with the drawing.
 */
export function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.floor(entry?.contentRect.width ?? 0));
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
  return [ref, width] as const;
}
