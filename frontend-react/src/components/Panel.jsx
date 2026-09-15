import React from 'react';
import { classNames } from '../utils/uiUtils';

/**
 * Thin wrapper over the .card/.card-elevated CSS classes already used
 * everywhere in core, so an addon's own component gets the same surface
 * (background, border, shadow) instead of reinventing it per addon.
 */
function Panel({ as: Component = 'div', elevated = false, className = '', children, ...rest }) {
  return (
    <Component className={classNames(elevated ? 'card-elevated' : 'card', 'p-4', className)} {...rest}>
      {children}
    </Component>
  );
}

export default Panel;
