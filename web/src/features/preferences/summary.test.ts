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
});
