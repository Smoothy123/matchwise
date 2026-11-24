/** Realistic API objects for tests, shaped by the generated types so they can't drift. */
import type { Health, Job, Match, Profile } from '../api/client';

export const HEALTHY: Health = {
  status: 'ok',
  jobs: 5450,
  active_jobs: 5000,
  embedded_jobs: 5000,
  llm_configured: true,
};

export const NO_LLM: Health = { ...HEALTHY, llm_configured: false };

export function makeProfile(overrides: Partial<Profile> = {}): Profile {
  return {
    profile_id: 'p1',
    version: 2,
    preferences: {
      wants: {
        roles: ['registered nurse'],
        skills: [],
        locations: ['Texas'],
        industries: [],
        seniority: [],
        remote: null,
        min_salary: null,
        other: [],
      },
      dealbreakers: {
        exclude_title_words: [],
        exclude_functions: [],
        exclude_industries: [],
        exclude_companies: [],
        exclude_description_phrases: ['night shift'],
        exclude_seniority: [],
        exclude_employment_types: [],
        only_locations: [],
        only_remote: false,
        min_salary: null,
      },
    },
    ...overrides,
  };
}

export function makeMatch(overrides: Partial<Match> = {}): Match {
  return {
    job_id: 5083,
    title: 'Registered Nurse, Emergency Room',
    company: 'Houston Methodist',
    location: 'Houston, TX',
    remote: false,
    seniority: 'mid_senior',
    employment_type: 'Full-time',
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    posted_at: '2024-04-21T00:26:13Z',
    skills: ['patient care', 'registered nurse'],
    matched_skills: [],
    score: 0.8574,
    similarity: 0.6164,
    features: {
      similarity: { value: 0.814, weight: 0.6923, contribution: 0.5635 },
      location: { value: 1, weight: 0.2308, contribution: 0.2308 },
      recency: { value: 0.8203, weight: 0.0769, contribution: 0.0631 },
    },
    explanation: null,
    limit_check: 'passed',
    ...overrides,
  };
}

export const REASON = {
  reason: 'A Registered Nurse role in Houston, Texas, matching your role and place.',
  matched_preferences: ['role: registered nurse', 'place: Texas'],
  caveats: ['Not listed as remote', 'Salary not stated', 'Benefits not stated'],
};

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 5083,
    title: 'Registered Nurse, Emergency Room',
    company: 'Houston Methodist',
    location: 'Houston, TX',
    remote: false,
    seniority: 'mid_senior',
    employment_type: 'Full-time',
    functions: ['Health Care Provider'],
    industries: ['Hospitals and Health Care'],
    skills: ['patient care', 'registered nurse'],
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    posted_at: '2024-04-21T00:26:13Z',
    description: 'Day shifts in the emergency room.\nBLS and ACLS required.',
    is_active: true,
    ...overrides,
  };
}

// ---------- chat history rows, as GET /profiles/{id}/chat returns them ----------

import type { ChatMessage } from '../api/client';

const AT = '2026-11-24T12:00:00Z';

export const chatRows = {
  user: (turn: number, content: string): ChatMessage => ({
    turn,
    role: 'user',
    content,
    tool_calls: null,
    tool_call_id: null,
    created_at: AT,
  }),
  toolRequest: (turn: number, calls: [id: string, name: string, args: object][]): ChatMessage => ({
    turn,
    role: 'assistant',
    content: null,
    tool_calls: calls.map(([id, name, args]) => ({
      id,
      function: { name, arguments: JSON.stringify(args) },
    })),
    tool_call_id: null,
    created_at: AT,
  }),
  toolResult: (turn: number, id: string, outcome: object): ChatMessage => ({
    turn,
    role: 'tool',
    content: JSON.stringify(outcome),
    tool_calls: null,
    tool_call_id: id,
    created_at: AT,
  }),
  reply: (turn: number, content: string): ChatMessage => ({
    turn,
    role: 'assistant',
    content,
    tool_calls: null,
    tool_call_id: null,
    created_at: AT,
  }),
};

// ---------- search ----------

import type { SearchResult } from '../api/client';

export function makeResults(query: string, count: number): SearchResult[] {
  return Array.from({ length: count }, (_, i) => ({
    id: 1000 + i,
    title: `${query} job ${String(i + 1)}`,
    company: 'Acme',
    location: 'Austin, TX',
    remote: i % 2 === 0,
    seniority: 'mid_senior',
    skills: ['python', 'sql'],
    snippet: 'A posting about this role',
    similarity: 0.6 - i * 0.01,
  }));
}
