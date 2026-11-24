import { Link } from 'react-router';

import type { HistoryItem, Preferences } from '../../api/client';
import { usePreferenceHistory, useProfile } from '../../api/queries';
import { formatDateTime } from '../../lib/format';
import { EmptyState } from '../../ui/EmptyState';
import { ErrorState } from '../../ui/ErrorState';
import { PageHeader } from '../../ui/PageHeader';
import { Skeleton } from '../../ui/Skeleton';
import { useProfileId } from '../profile/profileId';
import {
  describeOperation,
  FIELD_LABELS,
  fieldValues,
  LIMIT_FIELDS,
  WANT_FIELDS,
  type FieldPath,
} from './fields';
import styles from './PreferencesPage.module.css';

export default function PreferencesPage() {
  const profileId = useProfileId();
  const profile = useProfile(profileId);
  const history = usePreferenceHistory(profileId);

  let body;
  if (profile.isPending) {
    body = (
      <div className={styles.loading} role="status">
        <span className="visually-hidden">Loading your preferences…</span>
        <Skeleton height="8rem" />
        <Skeleton height="8rem" />
      </div>
    );
  } else if (profile.isError) {
    body = (
      <ErrorState
        title="Couldn't load your preferences"
        error={profile.error}
        onRetry={() => void profile.refetch()}
        retrying={profile.isFetching}
      />
    );
  } else if (profile.data === null) {
    body = (
      <EmptyState
        title="Nothing saved yet"
        action={<Link to="/">Tell the chat what you&apos;re looking for</Link>}
      >
        <p>Your preferences appear here once you&apos;ve described the job you want.</p>
      </EmptyState>
    );
  } else {
    const { preferences, version } = profile.data;
    body = (
      <>
        <div className={styles.current}>
          <FieldList
            title="What you want"
            hint="Ranks jobs: the more of these a job meets, the higher it goes."
            preferences={preferences}
            fields={WANT_FIELDS}
          />
          <FieldList
            title="Hard limits"
            hint="Rules jobs out: a job that breaks one is never shown."
            preferences={preferences}
            fields={LIMIT_FIELDS}
          />
        </div>
        <section className={styles.timeline} aria-labelledby="timeline-title">
          <h2 id="timeline-title">How each message changed them</h2>
          <p className={styles.hint}>
            The language model turns each message into explicit changes, so nothing earlier is
            silently dropped. Version {version} is the current one.
          </p>
          {history.isPending ? (
            <Skeleton height="6rem" />
          ) : history.isError ? (
            <ErrorState
              title="Couldn't load the history"
              error={history.error}
              onRetry={() => void history.refetch()}
              retrying={history.isFetching}
            />
          ) : (
            <ol className={styles.messages}>
              {history.data.map((item) => (
                <HistoryEntry key={item.version} item={item} />
              ))}
            </ol>
          )}
        </section>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="My preferences"
        description={
          <>
            What Matchwise has understood from your messages. To change anything,{' '}
            <Link to="/">say so in the chat</Link>.
          </>
        }
      />
      <div className={styles.body}>{body}</div>
    </>
  );
}

interface FieldListProps {
  title: string;
  hint: string;
  preferences: Preferences;
  fields: FieldPath[];
}

function FieldList({ title, hint, preferences, fields }: FieldListProps) {
  const set = fields
    .map((path) => ({ path, values: fieldValues(preferences, path) }))
    .filter((field) => field.values.length > 0);
  return (
    <section className={styles.card} aria-label={title}>
      <h2>{title}</h2>
      <p className={styles.hint}>{hint}</p>
      {set.length === 0 ? (
        <p className={styles.none}>None yet.</p>
      ) : (
        <dl className={styles.fields}>
          {set.map(({ path, values }) => (
            <div key={path} className={styles.field}>
              <dt>{FIELD_LABELS[path]}</dt>
              <dd>
                <ul className={styles.values}>
                  {values.map((value) => (
                    <li key={value}>{value}</li>
                  ))}
                </ul>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

const MARKS = { add: '+', remove: '−', set: '=', clear: '×' } as const;

function HistoryEntry({ item }: { item: HistoryItem }) {
  return (
    <li className={styles.entry}>
      <p className={styles.entryHead}>
        <span className={styles.version}>Version {item.version}</span>
        <time dateTime={item.created_at}>{formatDateTime(item.created_at)}</time>
      </p>
      <blockquote className={styles.said}>
        {/* Through the chat, this is the agent's light rewording of what you said. */}
        <span className="visually-hidden">Message: </span>
        {item.content}
      </blockquote>
      {item.operations.length === 0 ? (
        <p className={styles.none}>No changes: nothing in this message was a preference.</p>
      ) : (
        <ul className={styles.changes} aria-label="Changes">
          {item.operations.map((operation, i) => {
            const change = describeOperation(operation);
            return (
              <li key={i} className={styles[change.kind]}>
                <span className={styles.mark} aria-hidden="true">
                  {MARKS[change.kind]}
                </span>
                <span>
                  {change.text}
                  <span className={styles.evidence}>, from “{operation.evidence}”</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {item.notes.map((note) => (
        <p key={note} className={styles.note}>
          {note}
        </p>
      ))}
      <p className={styles.meta}>
        Read by {item.model} with prompt {item.prompt_version}
      </p>
    </li>
  );
}
