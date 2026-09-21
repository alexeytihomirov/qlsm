import React, { useMemo } from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { X } from 'lucide-react';
import AddonPanel from './AddonPanel';
import { resolveAddonIcon } from './addonIcons';
import { mountEntriesForAddon } from '../../contexts/AddonsContext';

/**
 * One addon's own settings, opened from the gear icon on its Addons-page
 * card. Renders the addon's declared `settings_section` mounts. They live
 * here rather than on the QLSM Settings page, which is for QLSM's own
 * settings: an addon's configuration belongs where the addon itself is.
 */
function AddonSettingsModal({ addon, isOpen, onClose }) {
  const mounts = useMemo(
    () => (addon ? mountEntriesForAddon(addon, 'settings_section') : []),
    [addon],
  );
  if (!addon) return null;
  const Icon = resolveAddonIcon(addon.ui?.icon);

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
              <Dialog.Title className="truncate text-base font-semibold text-theme-primary">
                {addon.name} settings
              </Dialog.Title>
            </div>
            <button type="button" onClick={onClose} aria-label="Close"
                    className="flex-shrink-0 rounded-md p-1 text-theme-muted hover:text-theme-primary">
              <X size={18} />
            </button>
          </div>

          <div className="px-5 py-4">
            {mounts.length === 0 && (
              <p className="py-2 text-sm text-theme-muted">This addon has no settings.</p>
            )}
            {mounts.map((mount, index) => {
              const SectionIcon = resolveAddonIcon(mount.icon);
              return (
                <div key={mount.key} className={index > 0 ? 'mt-6' : ''}>
                  <div className="mb-2 flex items-center gap-2">
                    <SectionIcon size={15} className="text-theme-muted" />
                    <h3 className="text-sm font-semibold text-theme-primary">{mount.label}</h3>
                  </div>
                  <AddonPanel addon={mount.addon} entry={mount.entry} panel={mount.panel}
                              scope={mount.scope} scopeId={0} />
                </div>
              );
            })}
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}

export default AddonSettingsModal;
