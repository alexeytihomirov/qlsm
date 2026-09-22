import React from 'react';
import { resolveAddonIcon } from './addonIcons';

/**
 * Icon by name, resolved from the same allow-list core uses for manifest
 * icons (see addonIcons.js). Lets an addon's own component render icons
 * without bundling lucide-react itself -- which would both bloat the bundle
 * and risk a visual set that drifts from core's.
 */
function Icon({ name, size = 16, className = '', ...rest }) {
  const IconComponent = resolveAddonIcon(name);
  return <IconComponent size={size} className={className} {...rest} />;
}

export default Icon;
