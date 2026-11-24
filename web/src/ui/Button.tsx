import { forwardRef, type ButtonHTMLAttributes } from 'react';

import styles from './Button.module.css';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'md' | 'sm';
}

// forwardRef so callers can focus the button (React 18; React 19 passes ref as a normal prop).
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    className,
    type = 'button', // a plain <button> inside a form would submit it by default
    ...props
  },
  ref,
) {
  const classes = [styles.button, styles[variant], styles[size], className].filter(Boolean);
  return <button ref={ref} type={type} className={classes.join(' ')} {...props} />;
});
