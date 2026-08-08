import React from 'react';
import { Archive } from 'lucide-react';
import ExportBackupPanel from '../components/backup/ExportBackupPanel';
import ImportBackupPanel from '../components/backup/ImportBackupPanel';

function BackupRestorePage() {
  return (
    <div className="users-page">
      <div className="users-page-header">
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <Archive className="users-page-title-icon" strokeWidth={2} />
            <h1 className="users-page-title">Backup &amp; Restore</h1>
          </div>
        </div>
      </div>

      <div className="users-page-header" style={{ marginTop: '0.5rem' }}>
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <h2 className="users-page-title" style={{ fontSize: '20px' }}>Export</h2>
          </div>
        </div>
      </div>
      <ExportBackupPanel />

      <div className="users-page-header" style={{ marginTop: '1.5rem' }}>
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <h2 className="users-page-title" style={{ fontSize: '20px' }}>Import</h2>
          </div>
        </div>
      </div>
      <ImportBackupPanel />
    </div>
  );
}

export default BackupRestorePage;
