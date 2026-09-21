import React, { useState } from 'react';
import { Menu } from '@headlessui/react';
import AddonComponentHost from './AddonComponentHost';
import AddonErrorBoundary from './AddonErrorBoundary';
import AddonModal from './AddonModal';
import { resolveAddonIcon } from './addonIcons';
import { rendersOwnModal } from './addonEntry';
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
 * `entity` is the whole host/instance object, not just its id: an addon that
 * supplies its own dialog gets it through `ctx.modal.entity`, because a
 * purpose-built screen usually shows the thing's name, port and so on -- not
 * only its id.
 *
 * Usage in a menu component:
 *
 *   const addonMenu = useAddonMenu('host_menu', host);
 *   return (<>
 *     {addonMenu.modal}
 *     <Menu>... <Menu.Items>... {addonMenu.items(closeMenu)} </Menu.Items></Menu>
 *   </>);
 */
export function useAddonMenu(point, entity, subtitle) {
  const mounts = useAddonMounts(point);
  const [openMount, setOpenMount] = useState(null);
  const scopeId = entity?.id;

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

  // An addon may supply the whole dialog (`renders: "modal"` on a tier-2
  // component). Then core's modal shell is skipped entirely -- that is what
  // lets a feature keep its purpose-built screen on the way into an addon
  // instead of being flattened into the generic panel shell.
  const ownModal = openMount && rendersOwnModal(openMount.entry) && openMount.entry?.component;

  // Nothing is shown while the bundle loads: the operator clicked a menu
  // entry, and a flash of placeholder before the real dialog is worse than
  // the dialog simply appearing.
  const modal = ownModal ? (
    <AddonErrorBoundary addonId={openMount.addon?.id}>
      <AddonComponentHost
        addon={openMount.addon}
        entry={openMount.entry}
        scope={openMount.scope}
        scopeId={scopeId}
        modal={{
          isOpen: Boolean(openMount),
          onClose: () => setOpenMount(null),
          entity,
          subtitle,
        }}
      />
    </AddonErrorBoundary>
  ) : (
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
