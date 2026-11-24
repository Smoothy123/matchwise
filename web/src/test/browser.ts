/**
 * Stand-ins for browser APIs jsdom doesn't have. Installed before every test by setup.ts.
 * `viewport.atBottom` lets a test pretend the person has scrolled up (the end of the
 * conversation is off screen) and tell every IntersectionObserver about it.
 */
import { vi } from 'vitest';

type Callback = (entries: { isIntersecting: boolean; target: Element }[]) => void;

const observers = new Set<FakeIntersectionObserver>();

/** window.scrollTo, as installed for every test (jsdom has no layout, so nothing scrolls). */
export const scrollToMock = vi.fn();

export const viewport = {
  atBottom: true,
  setAtBottom(value: boolean) {
    this.atBottom = value;
    for (const observer of observers) observer.report();
  },
};

class FakeIntersectionObserver {
  private targets: Element[] = [];
  constructor(private readonly callback: Callback) {}
  observe(target: Element) {
    this.targets.push(target);
    observers.add(this);
    this.report();
  }
  disconnect() {
    observers.delete(this);
  }
  report() {
    this.callback(this.targets.map((target) => ({ isIntersecting: viewport.atBottom, target })));
  }
}

/** Every observed element reports this width (jsdom has no layout). */
export const CHART_WIDTH = 480;

class FakeResizeObserver {
  constructor(private readonly callback: (entries: { contentRect: { width: number } }[]) => void) {}
  observe() {
    this.callback([{ contentRect: { width: CHART_WIDTH } }]);
  }
  disconnect() {
    // nothing to clean up
  }
}

export function installBrowserStubs() {
  viewport.atBottom = true;
  observers.clear();
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
  vi.stubGlobal('ResizeObserver', FakeResizeObserver);
  scrollToMock.mockClear();
  vi.stubGlobal('scrollTo', scrollToMock);
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}
