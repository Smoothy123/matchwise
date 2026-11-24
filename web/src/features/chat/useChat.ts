import { useMutation, useMutationState, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { resetChat, sendChatMessage } from '../../api/client';
import { queryKeys, useChatHistory } from '../../api/queries';
import { groupTurns } from './turns';

export interface PendingMessage {
  message: string;
  submittedAt: number;
}

/**
 * The conversation and the two things that change it: sending a message and clearing it.
 *
 * A turn takes 20–30 s. While it runs, the person's message shows at once ("optimistic"), read
 * from the mutation itself rather than written into the cache, so there is nothing to roll back
 * if it fails. The mutation lives in TanStack Query's cache, not in this component, so leaving the
 * page and coming back mid-reply still shows the message waiting.
 */
export function useChat(profileId: string) {
  const queryClient = useQueryClient();
  const history = useChatHistory(profileId);
  const turns = useMemo(
    () => (history.data ? groupTurns(history.data) : undefined),
    [history.data],
  );
  const mutationKey = ['send-chat', profileId];

  const send = useMutation({
    mutationKey,
    mutationFn: (message: string) => sendChatMessage(profileId, message),
    onSuccess: async (reply) => {
      const refreshes = [queryClient.invalidateQueries({ queryKey: queryKeys.chat(profileId) })];
      if (reply.tool_calls.some((call) => call.name === 'update_preferences' && call.ok)) {
        // New preferences mean a new profile version, which moves every matches query to a new
        // key (see queryKeys.matches): refreshing the profile is all the Matches page needs.
        refreshes.push(
          queryClient.invalidateQueries({ queryKey: queryKeys.profile(profileId) }),
          queryClient.invalidateQueries({ queryKey: queryKeys.preferenceHistory(profileId) }),
        );
      }
      // Awaited, so the message stays "pending" until the saved turn is in the history: the
      // optimistic copy and the real one never show together.
      await Promise.all(refreshes);
    },
    // A timeout or a dropped connection doesn't mean the server gave up: reload the history to see.
    onError: () => queryClient.invalidateQueries({ queryKey: queryKeys.chat(profileId) }),
  });

  const pending = useMutationState({
    filters: { mutationKey, status: 'pending' },
    select: (mutation): PendingMessage => ({
      message: typeof mutation.state.variables === 'string' ? mutation.state.variables : '',
      submittedAt: mutation.state.submittedAt,
    }),
  });

  // How many turns there were when the last message was sent: if the history now has one more
  // with that message, the "failed" request actually reached the server, so it isn't a failure.
  const [turnsAtSend, setTurnsAtSend] = useState(0);
  const landed =
    turns !== undefined && turns.length > turnsAtSend && turns.at(-1)?.message === send.variables;
  // Checking send.isError in the same expression narrows `send`, so error is an Error here.
  const failed = send.isError && !landed ? { message: send.variables, error: send.error } : null;

  const submit = (message: string) => {
    setTurnsAtSend(turns?.length ?? 0);
    send.mutate(message);
  };

  const clear = useMutation({
    mutationFn: () => resetChat(profileId),
    onSuccess: () => {
      queryClient.setQueryData(queryKeys.chat(profileId), []);
      send.reset();
    },
  });

  return {
    history,
    turns,
    pending: pending.at(-1) ?? null,
    failed,
    submit,
    dismissFailure: () => {
      send.reset();
    },
    clear,
  };
}
