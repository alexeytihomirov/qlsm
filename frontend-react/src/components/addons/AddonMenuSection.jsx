import React, { useState } from 'react';
import { Menu } from '@headlessui/react';
import AddonModal from './AddonModal';
import { resolveAddonIcon } from './addonIcons';
import { useAddonMounts } from '../../contexts/AddonsContext';

/**
 * Addon entries for a host or instance action menu.
 *
 * Split into a hook plus two pieces because of a Headless UI constraint:
 * `Menu.Items` unmounts its children when the menu closes, and clicking an
 * entry closes the menu -- so a dialog rendered inside the menu would be torn
 * down the instant it opened. The items go inside the menu, the modal goes
 * outside it. HostActionsMenu already keeps its own confirmation modals
 * outside `<Menu>` for the same reason.
 *
 * Usage in a menu component:
 *
 *   const addonMenu = useAddonMenu('host_menu', host.id, host.name);
 *   return (<>
 *     {addonMenu.modal}
 *     <Menu>... <Menu.Items>... {addonMenu.items(closeMenu)} </Menu.Items></Menu>
 *   </>);
 */
export function useAddonMenu(point, scopeId, subtitle) {
  const mounts = useAddonMounts(point);
  const [openMount, setOpenMount] = useState(null);

  const items = (closeMenu) => {
    if (mounts.length === 0) return null;
    return (
      <div className="px-1 py-1" style={{ borderTop: '1px solid var(--surface-border)' }}>
        {mounts.map((mount) => {
          const Icon = resolveAddonIcon(mount.icon);
          return (
            <Menu.Item key={mount.key}>
              {({ active }) => (
                <button
                  type="button"
                  onClick={() => {
                    setOpenMount(mount);
                    if (typeof closeMenu === 'function') closeMenu();
                  }}
                  className={`group flex rounded-md items-center w-full px-3 py-2 text-sm transition-colors ${
                    active ? 'bg-black/[0.04] dark:bg-white/[0.06] text-theme-primary' : 'text-theme-secondary'
                  }`}
                >
                  <Icon size={15} className="mr-3 flex-shrink-0 text-theme-muted" />
                  {mount.label}
                </button>
              )}
            </Menu.Item>
          );
        })}
      </div>
    );
  };

  const modal = (
    <AddonModal
      isOpen={Boolean(openMount)}
      onClose={() => setOpenMount(null)}
      mount={openMount}
      scopeId={scopeId}
      subtitle={subtitle}
    />
  );

  return { mounts, items, modal };
}

export default useAddonMenu;
