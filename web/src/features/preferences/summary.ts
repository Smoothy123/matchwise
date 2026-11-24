/** Preferences as short phrases in plain words, e.g. for "Ranked for: …" above the matches. */
import type { Preferences } from '../../api/client';
import { formatMoney, seniorityLabel } from '../../lib/format';

export interface PreferenceSummary {
  wants: string[];
  limits: string[];
}

const quoted = (text: string) => `“${text}”`;
const levels = (values: string[]) => values.map((value) => seniorityLabel(value) ?? value);

function remotePreference(remote: boolean | null | undefined): string[] {
  if (remote === true) return ['remote'];
  if (remote === false) return ['on-site'];
  return [];
}

export function summarisePreferences({
  wants,
  dealbreakers: limits,
}: Preferences): PreferenceSummary {
  return {
    wants: [
      ...wants.roles,
      ...wants.skills,
      ...wants.locations,
      ...wants.industries,
      ...levels(wants.seniority),
      ...remotePreference(wants.remote),
      ...(wants.min_salary ? [`${formatMoney(wants.min_salary)}+ a year`] : []),
      ...wants.other,
    ],
    limits: [
      ...limits.exclude_title_words.map((word) => `no ${quoted(word)} in the title`),
      ...limits.exclude_functions.map((fn) => `no ${fn}`),
      ...limits.exclude_industries.map((industry) => `no ${industry}`),
      ...limits.exclude_companies.map((company) => `not ${company}`),
      ...limits.exclude_description_phrases.map((phrase) => `no ${quoted(phrase)}`),
      ...levels(limits.exclude_seniority).map((level) => `not ${level}`),
      ...limits.exclude_employment_types.map((type) => `not ${type}`),
      ...(limits.only_locations.length ? [`only in ${limits.only_locations.join(' or ')}`] : []),
      ...(limits.only_remote ? ['remote only'] : []),
      ...(limits.min_salary ? [`at least ${formatMoney(limits.min_salary)} a year`] : []),
    ],
  };
}
