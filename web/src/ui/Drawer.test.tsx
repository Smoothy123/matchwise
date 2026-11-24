import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Drawer } from './Drawer';

describe('Drawer', () => {
  it('closes from its button and from a click on the backdrop, not from a click inside', () => {
    const onClose = vi.fn();
    render(
      <Drawer open onClose={onClose} labelledBy="t">
        <h2 id="t">Details</h2>
        <p>Inside</p>
      </Drawer>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Details' });

    fireEvent.click(screen.getByText('Inside'));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(dialog); // the backdrop: a click that lands on the <dialog> itself
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Close details' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('opens with focus on the close button, and closes when told to', () => {
    const { rerender } = render(
      <Drawer open onClose={() => undefined} labelledBy="t">
        <h2 id="t">Details</h2>
      </Drawer>,
    );
    expect(screen.getByRole('button', { name: 'Close details' })).toHaveFocus();
    rerender(
      <Drawer open={false} onClose={() => undefined} labelledBy="t">
        <h2 id="t">Details</h2>
      </Drawer>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
