import React from 'react';
import AddonPanel from './AddonPanel';
import { resolveAddonIcon } from './addonIcons';
import { useAddonMounts } from '../../contexts/AddonsContext';

/**
 * Global settings sections contributed by addons, appended to the Settings
 * page. Renders nothing when no addon declares `settings_section`, so a QLSM
 * with no addons shows exactly the page it showed before.
 */
function AddonSettingsSections() {
  const mounts = useAddonMounts('settings_section');
  if (mounts.length === 0) return null;

  return (
    <>
      {mounts.map((mount) => {
        const Icon = resolveAddonIcon(mount.icon);
        return (
          <div key={mount.key} className="mt-8">
            <div className="flex items-center gap-2 mb-3">
              <Icon size={17} className="text-theme-muted" />
              <h2 className="users-page-title" style={{ fontSize: '20px' }}>{mount.label}</h2>
            </div>
            <div className="users-table-container p-4">
              <AddonPanel addon={mount.addon} entry={mount.entry} panel={mount.panel}
                          scope={mount.scope} scopeId={0} />
            </div>
          </div>
        );
      })}
    </>
  );
}

export default AddonSettingsSections;
