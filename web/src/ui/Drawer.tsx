import { useEffect, useRef, type ReactNode } from 'react';

import styles from './Drawer.module.css';

interface DrawerProps {
  open: boolean;
  /** Called for Escape and the close button; the owner decides what closing means. */
  onClose: () => void;
  labelledBy: string;
  children: ReactNode;
}

/**
 * A side panel on the native <dialog>: showModal() makes the page behind it inert, keeps focus
 * inside, and closes on Escape. Wide screens get a panel on the right, phones the full screen.
 */
export function Drawer({ open, onClose, labelledBy, children }: DrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      dialog.showModal();
      closeRef.current?.focus();
      return () => opener?.focus(); // back to the card the person came from
    }
    if (!open && dialog.open) dialog.close();
    return undefined;
  }, [open]);

  return (
    // The click handler below only adds "click the backdrop to close" for mouse users. Its
    // keyboard equivalent, Escape, is built into <dialog>, which the lint rule can't see.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
    <dialog
      ref={dialogRef}
      className={styles.drawer}
      aria-labelledby={labelledBy}
      onClose={() => {
        // Fires for Escape, and also after we close it ourselves; only the first needs handling.
        if (open) onClose();
      }}
      onClick={(event) => {
        // A click on the dimmed backdrop lands on the <dialog> itself, never on its content.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.panel}>
        <button ref={closeRef} type="button" className={styles.close} onClick={onClose}>
          <span aria-hidden="true">×</span>
          <span className="visually-hidden">Close details</span>
        </button>
        {children}
      </div>
    </dialog>
  );
}
