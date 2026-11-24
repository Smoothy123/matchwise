/**
 * Every preference field in words, and every change to one. The labels are keyed by the API's
 * own field type (generated from the schema), so if the backend adds a field, TypeScript reports
 * the missing label here instead of the page silently showing a raw path.
 */
import type { Operation, Preferences } from '../../api/client';
import { formatMoney, seniorityLabel } from '../../lib/format';

export type FieldPath = Operation['field'];

export const FIELD_LABELS: Record<FieldPath, string> = {
  'wants.roles': 'Roles',
  'wants.skills': 'Skills',
  'wants.locations': 'Places',
  'wants.industries': 'Industries',
  'wants.seniority': 'Level',
  'wants.remote': 'Remote or on-site',
  'wants.min_salary': "Pay you'd like",
  'wants.other': 'Anything else',
  'dealbreakers.exclude_title_words': 'Never in the title',
  'dealbreakers.exclude_functions': 'Job functions ruled out',
  'dealbreakers.exclude_industries': 'Industries ruled out',
  'dealbreakers.exclude_companies': 'Companies ruled out',
  'dealbreakers.exclude_description_phrases': 'Phrases ruled out',
  'dealbreakers.exclude_seniority': 'Levels ruled out',
  'dealbreakers.exclude_employment_types': 'Employment types ruled out',
  'dealbreakers.only_locations': 'Only in these places',
  'dealbreakers.only_remote': 'Remote only',
  'dealbreakers.min_salary': "Lowest pay you'd accept",
};

const isFieldPath = (key: string): key is FieldPath => key in FIELD_LABELS;
const ALL_FIELDS = Object.keys(FIELD_LABELS).filter(isFieldPath);
export const WANT_FIELDS = ALL_FIELDS.filter((path) => path.startsWith('wants.'));
export const LIMIT_FIELDS = ALL_FIELDS.filter((path) => path.startsWith('dealbreakers.'));

/** One value of a field in words: "Mid–senior level", "$90K a year", "remote". */
export function formatFieldValue(path: FieldPath, value: unknown): string {
  if (path.endsWith('seniority')) return seniorityLabel(String(value)) ?? String(value);
  if (path.endsWith('min_salary') && typeof value === 'number')
    return `${formatMoney(value)} a year`;
  if (path === 'wants.remote') return value === true ? 'remote' : 'on-site';
  if (path === 'dealbreakers.only_remote') return value === true ? 'yes' : 'no';
  return String(value);
}

/** The values currently set for a field, in words; empty when it isn't set. */
export function fieldValues(preferences: Preferences, path: FieldPath): string[] {
  const [section, key] = path.split('.');
  const fields: Record<string, unknown> =
    section === 'wants' ? preferences.wants : preferences.dealbreakers;
  const value = key === undefined ? undefined : fields[key];
  if (Array.isArray(value)) return value.map((item) => formatFieldValue(path, item));
  // Unset single values: null, or false for "remote only" (false is its default).
  if (
    value === null ||
    value === undefined ||
    (path === 'dealbreakers.only_remote' && value === false)
  ) {
    return [];
  }
  return [formatFieldValue(path, value)];
}

export interface ChangeText {
  kind: 'add' | 'remove' | 'set' | 'clear';
  text: string;
}

/** An operation the LLM extracted from a message, in words. */
export function describeOperation(operation: Operation): ChangeText {
  const label = FIELD_LABELS[operation.field];
  const value = formatFieldValue(operation.field, operation.value);
  switch (operation.op) {
    case 'add':
      return { kind: 'add', text: `Added “${value}” to ${label}` };
    case 'remove':
      return { kind: 'remove', text: `Removed “${value}” from ${label}` };
    case 'set':
      return { kind: 'set', text: `Set ${label} to ${value}` };
    case 'clear':
      return { kind: 'clear', text: `Cleared ${label}` };
  }
}
