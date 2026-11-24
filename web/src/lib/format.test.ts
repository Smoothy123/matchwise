import { describe, expect, it } from 'vitest';

import { formatDate, formatMoney, formatPay, seniorityLabel } from './format';

describe('formatPay', () => {
  it.each([
    [80_000, 95_000, 'USD', '$80K–$95K a year'],
    [91_520, 104_000, 'USD', '$91.5K–$104K a year'],
    [85_000, 85_000, 'USD', '$85K a year'],
    [85_000, null, 'USD', 'From $85K a year'],
    [null, 120_000, 'USD', 'Up to $120K a year'],
    [70_000, 90_000, 'CAD', 'CA$70K–CA$90K a year'],
    [70_000, null, null, 'From $70K a year'],
  ])('%s to %s %s → %s', (min, max, currency, expected) => {
    expect(formatPay(min, max, currency)).toBe(expected);
  });

  it('says nothing when the posting lists no pay', () => {
    expect(formatPay(null, null, null)).toBeNull();
  });

  it('copes with a currency code Intl does not know', () => {
    expect(formatMoney(50_000, 'XYZ1')).toBe('50,000 XYZ1');
  });
});

describe('formatDate', () => {
  it('uses the UTC date, so a time near midnight does not move it a day', () => {
    expect(formatDate('2024-04-21T00:26:13Z')).toBe('Apr 21, 2024');
    expect(formatDate(null)).toBeNull();
  });
});

describe('seniorityLabel', () => {
  it('reads levels in words and hides the unknown one', () => {
    expect(seniorityLabel('mid_senior')).toBe('Mid–senior level');
    expect(seniorityLabel('unknown')).toBeNull();
  });
});
