import { describe, expect, it } from 'vitest';

import type { Operation } from '../../api/client';
import { makeProfile } from '../../test/fixtures';
import { describeOperation, FIELD_LABELS, fieldValues, LIMIT_FIELDS, WANT_FIELDS } from './fields';

describe('fields', () => {
  it('covers all 18 fields of the API, split into wants and hard limits', () => {
    expect(Object.keys(FIELD_LABELS)).toHaveLength(18);
    expect(WANT_FIELDS).toHaveLength(8);
    expect(LIMIT_FIELDS).toHaveLength(10);
  });

  it('reads current values in words, and nothing for unset ones', () => {
    const { preferences } = makeProfile();
    preferences.wants.seniority = ['mid_senior', 'director'];
    preferences.wants.min_salary = 90_000;
    expect(fieldValues(preferences, 'wants.roles')).toEqual(['registered nurse']);
    expect(fieldValues(preferences, 'wants.seniority')).toEqual(['Mid–senior level', 'Director']);
    expect(fieldValues(preferences, 'wants.min_salary')).toEqual(['$90K a year']);
    expect(fieldValues(preferences, 'wants.remote')).toEqual([]); // null: no view either way
    expect(fieldValues(preferences, 'dealbreakers.only_remote')).toEqual([]); // false is the default

    preferences.wants.remote = false;
    preferences.dealbreakers.only_remote = true;
    expect(fieldValues(preferences, 'wants.remote')).toEqual(['on-site']);
    expect(fieldValues(preferences, 'dealbreakers.only_remote')).toEqual(['yes']);
  });
});

describe('describeOperation', () => {
  const op = (o: Partial<Operation>): Operation => ({
    op: 'add',
    field: 'wants.roles',
    value: 'nurse',
    evidence: 'x',
    ...o,
  });

  it('words each kind of change', () => {
    expect(describeOperation(op({}))).toEqual({ kind: 'add', text: 'Added “nurse” to Roles' });
    expect(
      describeOperation(
        op({ op: 'remove', field: 'dealbreakers.exclude_functions', value: 'Sales' }),
      ),
    ).toEqual({
      kind: 'remove',
      text: 'Removed “Sales” from Job functions ruled out',
    });
    expect(
      describeOperation(op({ op: 'set', field: 'dealbreakers.min_salary', value: 70_000 })),
    ).toEqual({
      kind: 'set',
      text: "Set Lowest pay you'd accept to $70K a year",
    });
    expect(describeOperation(op({ op: 'clear', field: 'wants.remote', value: null }))).toEqual({
      kind: 'clear',
      text: 'Cleared Remote or on-site',
    });
  });
});
