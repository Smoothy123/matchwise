import { Link } from 'react-router';

import { PageHeader } from '../ui/PageHeader';

export function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" description="There's no page at this address." />
      <Link to="/">Go to the chat</Link>
    </>
  );
}
