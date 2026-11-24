import { render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import { parseBlocks, ReplyText } from './ReplyText';

function renderReply(text: string) {
  const router = createMemoryRouter([{ path: '/', element: <ReplyText text={text} /> }]);
  return render(<RouterProvider router={router} />);
}

describe('parseBlocks', () => {
  it('splits paragraphs, bullet lists and numbered lists', () => {
    expect(
      parseBlocks('Here you go:\n* One\n- Two\n\n1. First\n2) Second\nThat is all.\nBye'),
    ).toEqual([
      { kind: 'paragraph', lines: ['Here you go:'] },
      { kind: 'bullets', items: ['One', 'Two'] },
      { kind: 'numbers', items: ['First', 'Second'] },
      { kind: 'paragraph', lines: ['That is all.', 'Bye'] },
    ]);
  });
});

describe('ReplyText', () => {
  it('renders lists, bold text and job references as links to their details', () => {
    renderReply('Two fit:\n* **Nurse** at Methodist [#5083]\n* Case Manager [#4001]');
    const items = within(screen.getByRole('list')).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0] as HTMLElement).getByText('Nurse').tagName).toBe('STRONG');
    expect(screen.getByRole('link', { name: 'Details for job #5083' })).toHaveAttribute(
      'href',
      '/?job=5083',
    );
  });

  it('never turns reply text into HTML', () => {
    const { container } = renderReply('<img src=x onerror="alert(1)"> **<b>hi</b>** [#12abc]');
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    expect(container).toHaveTextContent('<img src=x onerror="alert(1)"> <b>hi</b> [#12abc]');
    expect(screen.queryByRole('link')).toBeNull(); // "[#12abc]" isn't a job reference
  });
});
