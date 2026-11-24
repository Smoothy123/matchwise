/**
 * The API stores a conversation as rows: per turn, the person's message, then (if the agent used
 * tools) assistant rows that request tools and "tool" rows with their results, then the reply.
 * The UI thinks in turns: what you said, which tools ran (and whether they worked), the reply.
 */
import type { ChatMessage } from '../../api/client';

export interface ToolUse {
  name: string;
  /** JSON text, exactly as the model wrote it. */
  arguments: string;
  ok: boolean;
}

export interface Turn {
  turn: number;
  message: string;
  reply: string | null; // null only if a turn was saved without its reply
  tools: ToolUse[];
}

/** A tool result is {"result": ...} or {"error": ...}; the API itself defines ok as "no error". */
export function toolSucceeded(content: string | null): boolean {
  if (!content) return true;
  try {
    const parsed: unknown = JSON.parse(content);
    return !(typeof parsed === 'object' && parsed !== null && 'error' in parsed);
  } catch {
    return true; // not JSON: nothing says it failed
  }
}

export function groupTurns(rows: ChatMessage[]): Turn[] {
  const turns = new Map<number, Turn>();
  const toolsById = new Map<string, ToolUse>();
  for (const row of rows) {
    let turn = turns.get(row.turn);
    if (!turn) {
      turn = { turn: row.turn, message: '', reply: null, tools: [] };
      turns.set(row.turn, turn);
    }
    if (row.role === 'user') {
      turn.message = row.content ?? '';
    } else if (row.role === 'assistant' && row.tool_calls) {
      for (const call of row.tool_calls) {
        const use = { name: call.function.name, arguments: call.function.arguments, ok: true };
        turn.tools.push(use);
        toolsById.set(call.id, use);
      }
    } else if (row.role === 'tool') {
      const use = row.tool_call_id ? toolsById.get(row.tool_call_id) : undefined;
      if (use) use.ok = toolSucceeded(row.content);
    } else {
      turn.reply = row.content;
    }
  }
  return [...turns.values()];
}

/**
 * True when the agent tried to save preferences in this turn and no attempt worked. Seen live:
 * with the LLM busy (503), the save failed and the agent still replied "I have them noted!".
 * The API now appends a note to such replies; the UI also flags them from the tool results.
 */
export function preferencesNotSaved(turn: Turn): boolean {
  const saves = turn.tools.filter((tool) => tool.name === 'update_preferences');
  return saves.length > 0 && saves.every((tool) => !tool.ok);
}

const TOOL_LABELS: Record<string, string> = {
  update_preferences: 'Saved your preferences',
  get_matches: 'Looked up your matches',
  search_jobs: 'Searched the jobs',
  explain_match: 'Explained a job',
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

/** A tool's arguments as "key: value" pairs; the raw text if it isn't a JSON object. */
export function describeArguments(json: string): string[] {
  try {
    const parsed: unknown = JSON.parse(json || '{}');
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return [json];
    return Object.entries(parsed).map(
      ([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`,
    );
  } catch {
    return [json];
  }
}
