/**
 * Client-side sorting and filtering of the ranked list. The state lives in the URL
 * (?sort=pay&remote=1), so a view can be bookmarked or shared, survives a reload, and the
 * Back button works. Only non-default values are written, to keep URLs short.
 */
import type { Match } from '../../api/client';

/** A match with its place in the API's ranking, kept when the list is re-sorted. */
export interface RankedMatch extends Match {
  rank: number;
}

export const SORTS = {
  best: 'Best match',
  newest: 'Newest',
  pay: 'Highest pay',
} as const;

export type SortKey = keyof typeof SORTS;

export interface ViewOptions {
  sort: SortKey;
  remoteOnly: boolean;
  payListed: boolean;
  text: string;
}

export const DEFAULT_VIEW: ViewOptions = {
  sort: 'best',
  remoteOnly: false,
  payListed: false,
  text: '',
};

function isSortKey(value: string | null): value is SortKey {
  return value !== null && value in SORTS;
}

export function readView(params: URLSearchParams): ViewOptions {
  const sort = params.get('sort');
  return {
    sort: isSortKey(sort) ? sort : 'best', // an unknown value from a hand-edited URL falls back
    remoteOnly: params.get('remote') === '1',
    payListed: params.get('pay') === '1',
    text: params.get('q') ?? '',
  };
}

/** The view written into `params`, leaving other keys (such as ?job=) alone. */
export function writeView(params: URLSearchParams, view: ViewOptions): URLSearchParams {
  const next = new URLSearchParams(params);
  const set = (key: string, value: string | null) => {
    if (value) next.set(key, value);
    else next.delete(key);
  };
  set('sort', view.sort === 'best' ? null : view.sort);
  set('remote', view.remoteOnly ? '1' : null);
  set('pay', view.payListed ? '1' : null);
  set('q', view.text.trim() ? view.text : null);
  return next;
}

export function isFiltered(view: ViewOptions): boolean {
  return view.remoteOnly || view.payListed || view.text.trim() !== '';
}

function topPay(match: Match): number | null {
  return match.salary_max ?? match.salary_min;
}

function matchesText(match: Match, needle: string): boolean {
  const haystack = [match.title, match.company, match.location, ...match.skills]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

/** Missing values go last whichever way the list is sorted; ties keep the API's ranking. */
function compare(a: RankedMatch, b: RankedMatch, sort: SortKey): number {
  if (sort === 'newest' || sort === 'pay') {
    const [x, y] =
      sort === 'newest'
        ? [
            a.posted_at ? Date.parse(a.posted_at) : null,
            b.posted_at ? Date.parse(b.posted_at) : null,
          ]
        : [topPay(a), topPay(b)];
    if (x !== y) {
      if (x === null) return 1;
      if (y === null) return -1;
      return y - x;
    }
  }
  return a.rank - b.rank;
}

export function applyView(matches: RankedMatch[], view: ViewOptions): RankedMatch[] {
  const needle = view.text.trim().toLowerCase();
  return matches
    .filter((m) => !view.remoteOnly || m.remote)
    .filter((m) => !view.payListed || topPay(m) !== null)
    .filter((m) => !needle || matchesText(m, needle))
    .sort((a, b) => compare(a, b, view.sort));
}
