import React from 'react';
import { classNames } from '../utils/uiUtils';

const VARIANT_CLASSES = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  danger: 'btn-danger',
};

/**
 * Thin wrapper over the .btn-* CSS classes already used everywhere in core,
 * so an addon's own component gets the same button look -- including
 * hover/focus-visible/disabled states -- without redefining them itself.
 */
function Button({ variant = 'secondary', type = 'button', className = '', children, ...rest }) {
  return (
    <button
      type={type}
      className={classNames('btn', VARIANT_CLASSES[variant] || VARIANT_CLASSES.secondary, className)}
      {...rest}
    >
      {children}
    </button>
  );
}

export default Button;
