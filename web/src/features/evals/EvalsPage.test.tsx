import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { axeViolations } from '../../test/axe';
import { mockApi } from '../../test/fetch';
import { HEALTHY } from '../../test/fixtures';
import { renderApp } from '../../test/render';

function renderEvals() {
  // The page needs no API: the results are bundled. Only the header's health check calls it.
  const fetchMock = mockApi({ 'GET /health': HEALTHY });
  return { fetchMock, ...renderApp('/evals') };
}

describe('the evals page', () => {
  it('says plainly who made the labels', async () => {
    renderEvals();
    expect(await screen.findByText(/written by a language model \(Claude\)/)).toHaveTextContent(
      'labelled by: claude-opus-5-5',
    );
  });

  it('draws one chart per metric, and a table with every number', async () => {
    renderEvals();
    await screen.findByRole('heading', { level: 1, name: 'Evals' });
    const charts = screen.getAllByRole('figure');
    expect(charts.map((c) => within(c).getByRole('heading').textContent)).toEqual([
      'Precision@5',
      'Recall@20',
      'nDCG@10',
      'Limit violations@10',
    ]);
    const table = screen.getByRole('table', { name: /Ranking metrics by version/ });
    const filters = within(table).getByRole('row', { name: /Hard-limit filters/ });
    expect(
      within(filters)
        .getAllByRole('cell')
        .map((c) => c.textContent),
    ).toEqual(['0.13 (0.07–0.20)', '0.77 (0.55–0.95)', '0.56 (0.46–0.67)', '0.13']);
  });

  it('describes each step with changes computed from the data', async () => {
    renderEvals();
    const steps = await screen.findByRole('region', { name: 'What each step changed' });
    expect(steps).toHaveTextContent('Limit violations@10 0.42 → 0.13 (−0.29, better)');
    expect(steps).toHaveTextContent('Recall@20 0.74 → 0.63 (−0.10, worse)');
  });

  it('shows a bar’s details on keyboard focus, as on hover', async () => {
    renderEvals();
    const ndcg = (await screen.findAllByRole('figure'))[2] as HTMLElement;
    const bar = within(ndcg).getByRole('img', {
      name: '+ Hard-limit filters: 0.56, 95% interval 0.46 to 0.67',
    });
    fireEvent.focus(bar);
    expect(within(ndcg).getByText('Mean over 15 personas')).toBeInTheDocument();
    fireEvent.blur(bar);
    expect(within(ndcg).queryByText('Mean over 15 personas')).not.toBeInTheDocument();
  });

  it('has no problems axe can find', async () => {
    renderEvals();
    await screen.findAllByRole('figure');
    expect(await axeViolations()).toEqual([]);
  });
});
