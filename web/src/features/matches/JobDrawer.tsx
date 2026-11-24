import { useId } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router';

import type { Mode } from '../../api/client';

import { Drawer } from '../../ui/Drawer';
import { JobDetail } from './JobDetail';
import type { ReasonsState } from './useRankedMatches';
import type { RankedMatch } from './view';

/** ?job=1234 → 1234; anything else (missing, "abc", "-1", "1.5") → null. */
export function parseJobId(value: string | null): number | null {
  if (!value || !/^\d{1,15}$/.test(value)) return null;
  const id = Number(value);
  return id > 0 ? id : null;
}

interface JobDrawerProps {
  matches: RankedMatch[] | undefined;
  reasons: ReasonsState;
  /** The ranking version `matches` came from; null on pages without one (chat, search). */
  mode: Mode | null;
}

/**
 * The details panel, driven by the URL: ?job=<id> opens it. So a job's details can be linked to,
 * survive a reload, and the browser's Back button closes the panel, as people expect on phones.
 */
export function JobDrawer({ matches, reasons, mode }: JobDrawerProps) {
  const titleId = useId();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const jobId = parseJobId(params.get('job'));
  const match = matches?.find((m) => m.job_id === jobId);

  const close = () => {
    const state: unknown = location.state;
    const openedFromList =
      typeof state === 'object' && state !== null && 'fromList' in state && state.fromList === true;
    if (openedFromList) {
      void navigate(-1); // undo the history entry that opening added
    } else {
      // Opened from a shared link or a reload: just drop ?job= without leaving the page.
      const next = new URLSearchParams(params);
      next.delete('job');
      setParams(next, { replace: true });
    }
  };

  return (
    <Drawer open={jobId !== null} onClose={close} labelledBy={titleId}>
      {jobId !== null ? (
        <JobDetail jobId={jobId} match={match} reasons={reasons} mode={mode} titleId={titleId} />
      ) : null}
    </Drawer>
  );
}
