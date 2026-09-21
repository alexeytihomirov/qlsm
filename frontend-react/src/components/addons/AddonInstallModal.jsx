import React, { useRef, useState } from 'react';
import { Dialog, DialogBackdrop } from '@headlessui/react';
import { AlertTriangle, Loader2, Upload } from 'lucide-react';
import { installAddon } from '../../services/addons';

// Deliberately the same shape as RiskAcknowledgeModal (unencrypted backup
// export): an explicit tick before an irreversible, security-relevant action.
// The wording mirrors addons/TRUST.md -- if that document changes, this list
// changes with it.
const WHAT_AN_ADDON_GETS = [
  'The database: every host, instance, user and API key',
  'The SSH private keys that log into every managed game server',
  'Your Vultr API key, which can create and destroy paid servers',
  'Ansible and Terraform, i.e. arbitrary commands on every managed host',
];

function AddonInstallModal({ isOpen, onClose, onInstalled }) {
  const [file, setFile] = useState(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  const reset = () => {
    setFile(null);
    setAcknowledged(false);
    setInstalling(false);
    setError(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleClose = () => {
    if (installing) return;
    reset();
    onClose();
  };

  const handleInstall = async () => {
    if (!file || !acknowledged) return;
    setInstalling(true);
    setError(null);
    try {
      const result = await installAddon(file);
      reset();
      onInstalled(result);
    } catch (err) {
      setError(err?.response?.data?.error?.message || err?.message || 'Install failed');
      setInstalling(false);
    }
  };

  return (
    <Dialog open={isOpen} as="div" className="relative z-10" onClose={handleClose}>
      <DialogBackdrop className="modal-backdrop fixed inset-0" />
      <div className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full items-center justify-center p-4 text-center">
          <Dialog.Panel className="modal-panel w-full max-w-lg transform overflow-hidden p-6 text-left align-middle">
            <div className="accent-line-top" />

            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 dark:bg-[#FF3366]/10 border border-red-200 dark:border-[#FF3366]/30 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-red-600 dark:text-[#FF3366]" />
              </div>
              <div className="flex-1 min-w-0">
                <Dialog.Title as="h3" className="font-display text-lg font-semibold tracking-wide text-theme-primary">
                  Install an addon
                </Dialog.Title>
                <p className="mt-2 text-sm text-theme-secondary">
                  An addon is not sandboxed. Once installed it runs as part of QLSM, with:
                </p>
                <ul className="mt-2 text-sm text-theme-secondary list-disc pl-5 space-y-1">
                  {WHAT_AN_ADDON_GETS.map((item) => <li key={item}>{item}</li>)}
                </ul>
                <p className="mt-2 text-sm text-theme-secondary">
                  Only install addons from a source you would trust with the QLSM host itself.
                </p>

                <div className="mt-4">
                  <label htmlFor="addon-zip" className="block text-sm text-theme-primary mb-1">
                    Addon package (.zip)
                  </label>
                  <input
                    id="addon-zip"
                    ref={inputRef}
                    type="file"
                    accept=".zip,application/zip"
                    disabled={installing}
                    onChange={(e) => { setFile(e.target.files?.[0] || null); setError(null); }}
                    className="block w-full text-sm text-theme-secondary"
                  />
                </div>

                <label className="mt-4 flex items-start gap-2 text-sm text-theme-primary">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    disabled={installing}
                    onChange={(e) => setAcknowledged(e.target.checked)}
                    aria-label="I trust this addon's author with full access to QLSM"
                  />
                  <span>I trust this addon&apos;s author with full access to QLSM</span>
                </label>

                {error && (
                  <p className="mt-3 text-sm" style={{ color: 'var(--accent-danger)' }}>{error}</p>
                )}
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button type="button" className="btn btn-secondary" onClick={handleClose} disabled={installing}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger inline-flex items-center gap-2"
                disabled={!file || !acknowledged || installing}
                onClick={handleInstall}
              >
                {installing ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
                Install
              </button>
            </div>
          </Dialog.Panel>
        </div>
      </div>
    </Dialog>
  );
}

export default AddonInstallModal;
