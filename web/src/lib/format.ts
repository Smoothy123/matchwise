/**
 * How postings are shown in words. One locale on purpose: the postings are US LinkedIn jobs paid
 * in dollars, and en-US keeps "$120K" readable for everyone (en-IN would print "$1.2L"). It also
 * makes the output the same on every machine, which the tests rely on.
 */
const LOCALE = 'en-US';

const SENIORITY: Record<string, string> = {
  intern: 'Internship',
  entry: 'Entry level',
  associate: 'Associate',
  mid_senior: 'Mid–senior level',
  director: 'Director',
  executive: 'Executive',
};

/** A readable level, or null when the posting doesn't say ("unknown"). */
export function seniorityLabel(seniority: string): string | null {
  return SENIORITY[seniority] ?? null;
}

export function formatMoney(amount: number, currency = 'USD'): string {
  try {
    return new Intl.NumberFormat(LOCALE, {
      style: 'currency',
      currency,
      notation: 'compact',
      // Both bounds: with only a maximum, Node and Chrome disagree ("$80.0K" vs "$80K").
      minimumFractionDigits: 0,
      maximumFractionDigits: 1,
    }).format(amount);
  } catch {
    return `${amount.toLocaleString(LOCALE)} ${currency}`; // an unknown currency code
  }
}

/** "$80K–$95K a year", "From $80K a year", or null when the posting lists no pay. */
export function formatPay(
  min: number | null,
  max: number | null,
  currency: string | null,
): string | null {
  const code = currency ?? 'USD';
  if (min !== null && max !== null && min !== max) {
    return `${formatMoney(min, code)}–${formatMoney(max, code)} a year`;
  }
  if (min !== null && max !== null) return `${formatMoney(min, code)} a year`;
  if (min !== null) return `From ${formatMoney(min, code)} a year`;
  if (max !== null) return `Up to ${formatMoney(max, code)} a year`;
  return null;
}

const DATE = new Intl.DateTimeFormat(LOCALE, {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC', // the API's timestamps are UTC; local time could shift a date by a day
});

export function formatDate(iso: string | null): string | null {
  return iso ? DATE.format(new Date(iso)) : null;
}
