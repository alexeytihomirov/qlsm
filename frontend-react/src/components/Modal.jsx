import React from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { classNames } from '../utils/uiUtils';

const SIZE_CLASSES = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-2xl',
};

/**
 * Generic modal chrome: backdrop, sizing, an optional icon+title header, and
 * a footer action slot. ConfirmationModal is the confirm/cancel
 * specialization of this -- anything needing arbitrary body content should
 * use this directly instead of hand-rolling another Dialog.
 */
function Modal({
  isOpen,
  onClose,
  title,
  icon,
  children,
  footer,
  size = 'md',
  zIndexClass = 'z-10',
}) {
  const sizeClass = SIZE_CLASSES[size] || SIZE_CLASSES.md;

  return (
    <Dialog open={isOpen} as="div" className={classNames('relative', zIndexClass)} onClose={onClose}>
      <DialogBackdrop transition className="modal-backdrop fixed inset-0 transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0" />

      <div className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-4 text-center">
          <Dialog.Panel transition className={classNames(
            'modal-panel w-full transform overflow-hidden p-6 text-left align-middle transition-all transition data-[enter]:ease-out data-[enter]:duration-300 data-[leave]:ease-in data-[leave]:duration-200 data-[closed]:opacity-0 data-[closed]:translate-y-4 data-[closed]:scale-95',
            sizeClass,
          )}>
            {/* Accent line (dark mode only) */}
            <div className="accent-line-top" />

            <div className="flex items-start gap-4">
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
                <div className={title ? 'mt-2' : undefined}>{children}</div>
              </div>
            </div>

            {footer && <div className="mt-6 flex justify-end gap-3">{footer}</div>}
          </Dialog.Panel>
        </div>
      </div>
    </Dialog>
  );
}

export default Modal;
