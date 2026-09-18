import React from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { X } from 'lucide-react';
import AddonPanel from './AddonPanel';
import { resolveAddonIcon } from './addonIcons';

/**
 * Dialog shell for an addon panel opened from a host or instance action menu.
 *
 * Core owns the shell -- backdrop, title, close button, escape handling -- and
 * the addon supplies only the body, the same split the instance tab and the
 * full page use.
 */
function AddonModal({ isOpen, onClose, mount, scopeId, subtitle }) {
  if (!mount) return null;
  const Icon = resolveAddonIcon(mount.icon);

  return (
    <Dialog open={isOpen} onClose={onClose} className="relative z-50">
      <DialogBackdrop className="fixed inset-0 bg-black/50" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel
          className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-xl border shadow-xl"
          style={{ background: 'var(--surface-raised)', borderColor: 'var(--surface-border)' }}
        >
          <div className="flex items-start justify-between gap-4 border-b px-5 py-4"
               style={{ borderColor: 'var(--surface-border)' }}>
            <div className="flex items-center gap-3 min-w-0">
              <Icon size={18} className="flex-shrink-0 text-theme-muted" />
              <div className="min-w-0">
                <Dialog.Title className="truncate text-base font-semibold text-theme-primary">
                  {mount.label}
                </Dialog.Title>
                {subtitle && <p className="truncate text-xs text-theme-muted">{subtitle}</p>}
              </div>
            </div>
            <button type="button" onClick={onClose} aria-label="Close"
                    className="flex-shrink-0 rounded-md p-1 text-theme-muted hover:text-theme-primary">
              <X size={18} />
            </button>
          </div>

          <div className="px-5 py-4">
            <AddonPanel addon={mount.addon} entry={mount.entry} panel={mount.panel}
                        scope={mount.scope} scopeId={scopeId} />
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}

export default AddonModal;
