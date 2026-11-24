import '@testing-library/jest-dom/vitest';

import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll } from 'vitest';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

beforeAll(() => {
  // jsdom has no <dialog> behaviour (the DOM types say it does, hence the Partial). Enough of it
  // to test our logic; real browsers add the focus trap and Escape handling.
  const dialog = HTMLDialogElement.prototype as Partial<HTMLDialogElement>;
  if (typeof dialog.showModal !== 'function') {
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.setAttribute('open', '');
    };
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.removeAttribute('open');
      this.dispatchEvent(new Event('close'));
    };
  }
});
