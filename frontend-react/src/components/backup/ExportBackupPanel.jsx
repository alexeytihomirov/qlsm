import React, { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { exportBackup } from '../../services/api';
import { useNotification } from '../NotificationProvider';
import RiskAcknowledgeModal from './RiskAcknowledgeModal';

const labelClass = 'block text-sm font-medium text-theme-secondary mb-1.5';

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function ExportBackupPanel() {
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [exporting, setExporting] = useState(false);
  const [showRiskModal, setShowRiskModal] = useState(false);
  const { showSuccess, showError } = useNotification();

  const doExport = async (effectivePassword) => {
    setExporting(true);
    try {
      const { blob, filename } = await exportBackup(effectivePassword);
      downloadBlob(blob, filename);
      showSuccess('Backup exported.');
    } catch (err) {
      showError(err.error?.message || 'Failed to export backup.');
    } finally {
      setExporting(false);
    }
  };

  const handleExportClick = () => {
    if (password) {
      if (password !== confirmPassword) {
        showError('Password and confirmation do not match.');
        return;
      }
      doExport(password);
      return;
    }
    setShowRiskModal(true);
  };

  const handleRiskConfirmed = () => {
    setShowRiskModal(false);
    doExport(null);
  };

  return (
    <div className="users-table-container">
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '1rem', maxWidth: '360px' }}>
        <div>
          <label htmlFor="backup-password" className={labelClass}>Password</label>
          <input
            id="backup-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input-base"
            placeholder="Leave blank to export unencrypted"
          />
        </div>
        <div>
          <label htmlFor="backup-password-confirm" className={labelClass}>Confirm Password</label>
          <input
            id="backup-password-confirm"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="input-base"
          />
        </div>
        <p className="text-xs text-theme-secondary">
          Encrypting the backup with a password is strongly recommended — it protects SSH keys, API keys, and credentials stored in the archive.
        </p>
        <button
          onClick={handleExportClick}
          disabled={exporting}
          className="users-add-btn"
          style={{ alignSelf: 'flex-start' }}
        >
          {exporting ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} strokeWidth={2} />}
          <span>Export Backup</span>
        </button>
      </div>
      <RiskAcknowledgeModal
        isOpen={showRiskModal}
        onClose={() => setShowRiskModal(false)}
        onConfirm={handleRiskConfirmed}
      />
    </div>
  );
}

export default ExportBackupPanel;
