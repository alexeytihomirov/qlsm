import React from 'react';
import { classNames } from '../utils/uiUtils';

// Explicit, literal class names (not built with template strings) so
// Tailwind's content scanner -- which greps source text, not runtime
// values -- actually finds and keeps them.
const GAP_CLASSES = {
  0: 'gap-0', 1: 'gap-1', 2: 'gap-2', 3: 'gap-3', 4: 'gap-4', 5: 'gap-5', 6: 'gap-6', 8: 'gap-8',
};
const ALIGN_CLASSES = {
  start: 'items-start', center: 'items-center', end: 'items-end', stretch: 'items-stretch', baseline: 'items-baseline',
};
const JUSTIFY_CLASSES = {
  start: 'justify-start', center: 'justify-center', end: 'justify-end', between: 'justify-between', around: 'justify-around',
};

/** Vertical flex layout with a consistent gap scale. */
export function Stack({ gap = 3, align, justify, className = '', children, ...rest }) {
  return (
    <div
      className={classNames(
        'flex flex-col',
        GAP_CLASSES[gap] || GAP_CLASSES[3],
        align && ALIGN_CLASSES[align],
        justify && JUSTIFY_CLASSES[justify],
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

/** Horizontal flex layout with a consistent gap scale. */
export function Row({ gap = 3, align = 'center', justify, wrap = false, className = '', children, ...rest }) {
  return (
    <div
      className={classNames(
        'flex flex-row',
        wrap && 'flex-wrap',
        GAP_CLASSES[gap] || GAP_CLASSES[3],
        ALIGN_CLASSES[align],
        justify && JUSTIFY_CLASSES[justify],
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export default Stack;
