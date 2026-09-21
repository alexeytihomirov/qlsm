import React from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { classNames } from '../utils/uiUtils';

const SIZE_CLASSES = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-2xl',
  '2xl': 'max-w-[960px]',
};

/**
 * Generic modal chrome: backdrop, sizing, an optional icon+title header, and
 * a footer action slot. ConfirmationModal is the confirm/cancel
 * specialization of this -- anything needing arbitrary body content should
 * use this directly instead of hand-rolling another Dialog.
 *
 * `height` (e.g. '75vh') opts into a fixed-height panel with a scrolling
 * body, for content like a demo/log table that needs to fill the viewport
 * instead of growing with it. Omit it for the default auto-height panel.
 * `headerActions` renders extra buttons (refresh, close, ...) at the right
 * edge of the header, alongside the icon+title.
 */
function Modal({
  isOpen,
  onClose,
  title,
  icon,
  children,
  footer,
  headerActions,
  size = 'md',
  height,
  zIndexClass = 'z-10',
}) {
  const sizeClass = SIZE_CLASSES[size] || SIZE_CLASSES.md;
  const hasCustomHeight = Boolean(height);

  return (
    <Dialog open={isOpen} as="div" className={classNames('relative', zIndexClass)} onClose={onClose}>
      <DialogBackdrop transition className="modal-backdrop fixed inset-0 transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0" />

      <div className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-4 text-center">
          <Dialog.Panel
            transition
            style={hasCustomHeight ? { height } : undefined}
            className={classNames(
              'modal-panel w-full transform overflow-hidden p-6 text-left align-middle transition-all transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0 data-[closed]:translate-y-4 data-[closed]:scale-95',
              sizeClass,
              hasCustomHeight && 'flex flex-col',
            )}
          >
            {/* Accent line (dark mode only) */}
            <div className="accent-line-top" />

            <div className={classNames('flex items-start gap-4', hasCustomHeight && 'flex-shrink-0')}>
              {icon}
              <div className="flex-1 min-w-0">
                {title && (
                  <Dialog.Title
                    as="h3"
                    className="font-display text-lg font-semibold tracking-wide text-theme-primary"
                  >
                    {title}
                  </Dialog.Title>
                )}
                {!hasCustomHeight && (
                  <div className={title ? 'mt-2' : undefined}>{children}</div>
                )}
              </div>
              {headerActions && (
                <div className="flex items-center gap-2 flex-shrink-0">
                  {headerActions}
                </div>
              )}
            </div>

            {hasCustomHeight && (
              <div className={classNames('flex-1 overflow-auto', title ? 'mt-2' : undefined)}>
                {children}
              </div>
            )}

            {footer && (
              <div className={classNames('mt-6 flex justify-end gap-3', hasCustomHeight && 'flex-shrink-0')}>
                {footer}
              </div>
            )}
          </Dialog.Panel>
        </div>
      </div>
    </Dialog>
  );
}

export default Modal;
