import { useRouteError } from 'react-router';

import { Button } from '../ui/Button';
import { PageHeader } from '../ui/PageHeader';

/** Browsers word a failed dynamic import differently; all mean the page's code didn't arrive,
 * usually because a new version was deployed and the old chunk files are gone. */
const CHUNK_FAILED =
  /dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;

export function RouteError() {
  const error = useRouteError();
  const chunkFailed = error instanceof Error && CHUNK_FAILED.test(error.message);
  return (
    <div role="alert">
      <PageHeader
        title={chunkFailed ? "This page couldn't load" : 'Something went wrong'}
        description={
          chunkFailed
            ? 'Matchwise may have been updated since you opened it. Reloading gets the latest version.'
            : 'An unexpected error stopped this page. Reloading usually fixes it.'
        }
      />
      <Button
        variant="primary"
        onClick={() => {
          window.location.reload();
        }}
      >
        Reload
      </Button>
    </div>
  );
}
