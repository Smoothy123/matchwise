import { useId } from 'react';
import { Link, useSearchParams } from 'react-router';

import type { SearchResult } from '../../api/client';
import { useSearch } from '../../api/queries';
import { seniorityLabel } from '../../lib/format';
import { useDebouncedValue } from '../../lib/useDebouncedValue';
import { Button } from '../../ui/Button';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { PageHeader } from '../../ui/PageHeader';
import { Skeleton } from '../../ui/Skeleton';
import { JobDrawer } from '../matches/JobDrawer';
import { useJobLink } from '../matches/MatchCard';
import styles from './SearchPage.module.css';

export const DEBOUNCE_MS = 300;
export const PAGE = 10;
const MAX_LIMIT = 50; // the API's own maximum

const EXAMPLES = ['python backend engineer, remote', 'ICU nurse in Texas', 'not sales'];

/** ?limit= as a whole page count between PAGE and MAX_LIMIT; anything else means one page. */
export function readLimit(value: string | null): number {
  const n = Number(value);
  return Number.isInteger(n) && n >= PAGE && n <= MAX_LIMIT ? n - (n % PAGE) : PAGE;
}

export default function SearchPage() {
  const id = useId();
  const [params, setParams] = useSearchParams();
  // The box shows exactly what's in the URL, so Back, Forward and shared links need no extra
  // syncing. Only the request waits for a pause in typing.
  const text = params.get('q') ?? '';
  const limit = readLimit(params.get('limit'));
  const query = useDebouncedValue(text.trim(), DEBOUNCE_MS);
  const search = useSearch(query, limit);

  const setText = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set('q', value);
    else next.delete('q');
    next.delete('limit'); // a new search starts at the first page
    next.delete('job');
    setParams(next, { replace: true }); // replace: one Back step per search, not per keystroke
  };

  const showMore = () => {
    const next = new URLSearchParams(params);
    next.set('limit', String(limit + PAGE));
    setParams(next, { replace: true });
  };

  const typed = text.trim();
  let body;
  if (typed.length === 0) {
    body = (
      <div className={styles.intro}>
        <p>Try one of these:</p>
        <ul className={styles.examples}>
          {EXAMPLES.map((example) => (
            <li key={example}>
              <Link to={{ search: `?q=${encodeURIComponent(example)}` }}>{example}</Link>
            </li>
          ))}
        </ul>
      </div>
    );
  } else if (typed.length < 2) {
    body = <p className={styles.status}>Type at least 2 characters.</p>;
  } else if (search.isError) {
    body = (
      <ErrorState
        title="Couldn't search"
        error={search.error}
        onRetry={() => void search.refetch()}
        retrying={search.isFetching}
      />
    );
  } else if (!search.data) {
    body = (
      <div className={styles.results} role="status">
        <span className="visually-hidden">Searching…</span>
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} height="7rem" />
        ))}
      </div>
    );
  } else if (search.data.length === 0) {
    body = <EmptyState title="No open jobs found" />;
  } else {
    // Old results stay on screen, dimmed, while the new search runs (placeholderData).
    const stale = search.isPlaceholderData || query !== typed;
    body = (
      <>
        <ol
          className={`${styles.results} ${stale ? styles.stale : ''}`}
          aria-label="Results"
          aria-busy={stale}
        >
          {search.data.map((result) => (
            <li key={result.id}>
              <ResultCard result={result} />
            </li>
          ))}
        </ol>
        {search.data.length === limit && limit < MAX_LIMIT ? (
          <Button onClick={showMore} disabled={search.isFetching}>
            {search.isFetching ? 'Loading…' : `Show ${String(PAGE)} more`}
          </Button>
        ) : null}
      </>
    );
  }

  const count =
    search.data && typed.length >= 2 && !search.isPlaceholderData && query === typed
      ? `${String(search.data.length)} results for “${query}”`
      : '';

  return (
    <>
      <PageHeader
        title="Search"
        description="Look for jobs by meaning. This ignores your preferences and hard limits; your Matches page applies them."
      />
      <form
        role="search"
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault(); // results already follow the box as you type
        }}
      >
        <label htmlFor={`${id}-q`}>Search jobs</label>
        <input
          id={`${id}-q`}
          type="search"
          value={text}
          maxLength={500}
          placeholder="A role, skills, a place…"
          autoComplete="off"
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
      </form>
      <p className={styles.note}>
        Search compares meaning, so it can&apos;t follow &ldquo;not&rdquo;: &ldquo;not sales&rdquo;
        finds sales jobs. That&apos;s why your hard limits are applied as filters on the Matches
        page.
      </p>
      {/* Announced once the results for a finished query are in, not on every keystroke. */}
      <p aria-live="polite" className={styles.count}>
        {count}
      </p>
      <div className={styles.body}>{body}</div>
      <JobDrawer matches={undefined} reasons="off" />
    </>
  );
}

function ResultCard({ result }: { result: SearchResult }) {
  const titleId = useId();
  const jobLink = useJobLink(result.id);
  const facts = [result.remote ? 'Remote' : null, seniorityLabel(result.seniority)].filter(
    (fact): fact is string => Boolean(fact),
  );
  return (
    <article className={styles.card} aria-labelledby={titleId}>
      <div className={styles.head}>
        <h2 id={titleId} className={styles.title}>
          <Link to={jobLink} state={{ fromList: true }} className={styles.titleLink}>
            {result.title}
          </Link>
        </h2>
        <p className={styles.similarity}>
          <span className={styles.similarityLabel}>Similarity</span> {result.similarity.toFixed(2)}
        </p>
      </div>
      <p className={styles.where}>
        {[result.company, result.location].filter(Boolean).join(' · ') || 'Company not listed'}
      </p>
      {facts.length > 0 || result.skills.length > 0 ? (
        <ul className={styles.facts} aria-label="Key facts and skills">
          {facts.map((fact) => (
            <li key={fact} className={styles.fact}>
              {fact}
            </li>
          ))}
          {result.skills.slice(0, 5).map((skill) => (
            <li key={skill}>{skill}</li>
          ))}
        </ul>
      ) : null}
      <p className={styles.snippet}>{result.snippet.trim()}…</p>
    </article>
  );
}
