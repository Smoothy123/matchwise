import { describe, expect, it } from 'vitest';

import { makeProfile } from '../../test/fixtures';
import { summarisePreferences } from './summary';

describe('summarisePreferences', () => {
  it('lists wants and hard limits in plain words', () => {
    const { preferences } = makeProfile();
    preferences.wants.remote = true;
    preferences.wants.seniority = ['mid_senior'];
    preferences.wants.min_salary = 90_000;
    preferences.dealbreakers.only_locations = ['Austin, TX', 'Dallas, TX'];
    preferences.dealbreakers.exclude_title_words = ['travel'];
    expect(summarisePreferences(preferences)).toEqual({
      wants: ['registered nurse', 'Texas', 'Mid–senior level', 'remote', '$90K+ a year'],
      limits: ['no “travel” in the title', 'no “night shift”', 'only in Austin, TX or Dallas, TX'],
    });
  });

  it('is empty for an empty profile', () => {
    const { preferences } = makeProfile();
    preferences.wants.roles = [];
    preferences.wants.locations = [];
    preferences.dealbreakers.exclude_description_phrases = [];
    expect(summarisePreferences(preferences)).toEqual({ wants: [], limits: [] });
  });

  it('words every kind of hard limit', () => {
    const { preferences } = makeProfile();
    preferences.dealbreakers = {
      exclude_title_words: [],
      exclude_functions: ['Sales'],
      exclude_industries: ['Staffing'],
      exclude_companies: ['Acme'],
      exclude_description_phrases: [],
      exclude_seniority: ['intern'],
      exclude_employment_types: ['Contract'],
      only_locations: [],
      only_remote: true,
      min_salary: 70_000,
    };
    preferences.wants.remote = false;
    expect(summarisePreferences(preferences).limits).toEqual([
      'no Sales',
      'no Staffing',
      'not Acme',
      'not Internship',
      'not Contract',
      'remote only',
      'at least $70K a year',
    ]);
    expect(summarisePreferences(preferences).wants).toContain('on-site');
  });
});
