import React, { Suspense, useState } from 'react';
import { Menu } from '@headlessui/react';
import AddonModal from './AddonModal';
import { resolveAddonIcon } from './addonIcons';
import { rendersOwnModal, resolveBundledComponent } from './bundledPanels';
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
 * `entity` is the whole host/instance object, not just its id: a bundled
 * addon can mount the same purpose-built modal core mounts, and those take
 * the entity (they show its name, port and so on).
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

  // A bundled addon may supply the whole dialog. Then core's modal shell is
  // skipped entirely -- that is what makes the addon entry pixel-identical to
  // the built-in one instead of merely similar.
  const OwnModal = openMount && rendersOwnModal(openMount.entry)
    ? resolveBundledComponent(openMount.addon, openMount.entry)
    : null;

  // Suspense because the bundled components are lazily loaded (see
  // bundledPanels). Nothing is shown while it loads: the operator clicked a
  // menu entry, and a flash of placeholder before the real dialog is worse
  // than the dialog simply appearing.
  const modal = OwnModal ? (
    <Suspense fallback={null}>
      <OwnModal isOpen={Boolean(openMount)} onClose={() => setOpenMount(null)} entity={entity} />
    </Suspense>
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
