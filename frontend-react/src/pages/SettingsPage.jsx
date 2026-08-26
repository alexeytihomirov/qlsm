import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Copy, KeyRound, Loader2, AlertCircle, Trash2 } from 'lucide-react';
import { getApiKey, regenerateApiKey, revokeApiKey, getVultrKeySetting, setVultrKeySetting, getStatsHubSetting, setStatsHubSetting } from '../services/api';
import { useNotification } from '../components/NotificationProvider';
import ConfirmationModal from '../components/ConfirmationModal';
import { formatDateTime } from '../utils/uiUtils';
import { copyToClipboard } from '../utils/clipboard';

function SettingsPage() {
  const [apiKey, setApiKey] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [regenerating, setRegenerating] = useState(false);
  const [showRevokeModal, setShowRevokeModal] = useState(false);

  const [vultrKey, setVultrKey] = useState('');
  const [vultrKeyInput, setVultrKeyInput] = useState('');
  const [savingVultrKey, setSavingVultrKey] = useState(false);

  const [statsHubUrl, setStatsHubUrl] = useState('');
  const [statsHubUrlInput, setStatsHubUrlInput] = useState('');
  const [statsHubToken, setStatsHubToken] = useState('');
  const [statsHubTokenInput, setStatsHubTokenInput] = useState('');
  const [savingStatsHub, setSavingStatsHub] = useState(false);

  const { showSuccess, showError } = useNotification();

  const fetchApiKey = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const keyData = await getApiKey();
      setApiKey(keyData);
    } catch (err) {
      setError(err.error?.message || 'Failed to load API key.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchApiKey(); }, [fetchApiKey]);

  const fetchVultrKey = useCallback(async () => {
    try {
      const data = await getVultrKeySetting();
      setVultrKey(data.key || '');
      setVultrKeyInput(data.key || '');
    } catch {
      // Non-fatal — the rest of the page still works without this field.
    }
  }, []);

  useEffect(() => { fetchVultrKey(); }, [fetchVultrKey]);

  const handleSaveVultrKey = async () => {
    setSavingVultrKey(true);
    try {
      const data = await setVultrKeySetting(vultrKeyInput);
      setVultrKey(data.key || '');
      showSuccess('Vultr API key updated.');
    } catch (err) {
      showError(err.error?.message || 'Failed to update Vultr API key.');
    } finally {
      setSavingVultrKey(false);
    }
  };

  const fetchStatsHub = useCallback(async () => {
    try {
      const data = await getStatsHubSetting();
      setStatsHubUrl(data.url || '');
      setStatsHubUrlInput(data.url || '');
      setStatsHubToken(data.ingest_token || '');
      setStatsHubTokenInput(data.ingest_token || '');
    } catch {
      // Non-fatal — the rest of the page still works without this field.
    }
  }, []);

  useEffect(() => { fetchStatsHub(); }, [fetchStatsHub]);

  const handleSaveStatsHub = async () => {
    setSavingStatsHub(true);
    try {
      const data = await setStatsHubSetting(statsHubUrlInput, statsHubTokenInput);
      setStatsHubUrl(data.url || '');
      setStatsHubToken(data.ingest_token || '');
      showSuccess('Stats-hub target updated.');
    } catch (err) {
      showError(err.error?.message || 'Failed to update stats-hub target.');
    } finally {
      setSavingStatsHub(false);
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const newKey = await regenerateApiKey();
      setApiKey(newKey);
      showSuccess(apiKey ? 'API key regenerated.' : 'New API key generated.');
    } catch (err) {
      showError(err.error?.message || 'Failed to regenerate key.');
    } finally {
      setRegenerating(false);
    }
  };

  const handleRevoke = async () => {
    try {
      await revokeApiKey();
      setApiKey(null);
      showSuccess('API key revoked.');
    } catch (err) {
      showError(err.error?.message || 'Failed to revoke key.');
    }
    setShowRevokeModal(false);
  };

  const handleCopy = () => {
    if (apiKey?.key) {
      copyToClipboard(apiKey.key);
      showSuccess('API key copied to clipboard.');
    }
  };

  if (error) {
    return (
      <div className="users-page">
        <div className="users-page-header">
          <div className="users-page-title-row">
            <div className="users-page-title-wrapper">
              <KeyRound className="users-page-title-icon" strokeWidth={2} />
              <h1 className="users-page-title">External API</h1>
            </div>
          </div>
        </div>
        <div className="users-error-state">
          <AlertCircle size={24} strokeWidth={2} style={{ color: 'var(--accent-danger)' }} />
          <p className="users-error-text">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="users-page">
      {/* Page header */}
      <div className="users-page-header">
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <KeyRound className="users-page-title-icon" strokeWidth={2} />
            <h1 className="users-page-title">External API</h1>
          </div>
          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="users-add-btn"
          >
            {regenerating
              ? <Loader2 size={18} className="animate-spin" />
              : apiKey
                ? <RefreshCw size={18} strokeWidth={2} />
                : <KeyRound size={18} strokeWidth={2} />
            }
            <span>{apiKey ? 'Regenerate Key' : 'Generate Key'}</span>
          </button>
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="users-loading-state">
          <Loader2 className="users-loading-spinner" strokeWidth={2} />
          <span className="users-loading-text">Loading API key...</span>
        </div>
      ) : !apiKey ? (
        <div className="users-empty-state">
          <KeyRound size={32} strokeWidth={1.5} className="users-empty-icon" />
          <p className="users-empty-text">No API key generated yet.</p>
        </div>
      ) : (
        <div className="users-table-container">
          <table className="users-table">
            <thead>
              <tr>
                <th className="users-th">API Key</th>
                <th className="users-th">Created</th>
                <th className="users-th users-th-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr className="users-tr">
                <td className="users-td">
                  <div className="settings-key-group">
                    <span className="settings-key-cell">{apiKey.key}</span>
                    <button
                      onClick={handleCopy}
                      className="users-action-btn users-action-btn-reset settings-copy-btn"
                      title="Copy to clipboard"
                    >
                      <Copy size={14} strokeWidth={2} />
                    </button>
                  </div>
                </td>
                <td className="users-td">
                  <span className="users-td-date">{formatDateTime(apiKey.created_at)}</span>
                </td>
                <td className="users-td users-td-actions">
                  <button
                    onClick={() => setShowRevokeModal(true)}
                    className="users-action-btn users-action-btn-delete"
                    title="Revoke API key"
                  >
                    <Trash2 size={16} strokeWidth={2} />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {/* Vultr API key */}
      <div className="users-page-header" style={{ marginTop: '2rem' }}>
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <h2 className="users-page-title" style={{ fontSize: '20px' }}>Vultr API Key</h2>
          </div>
        </div>
      </div>
      <div className="users-table-container">
        <div style={{ display: 'flex', gap: '0.75rem', padding: '16px 20px', alignItems: 'center' }}>
          <label htmlFor="vultr-api-key" className="sr-only">Vultr API Key</label>
          <input
            id="vultr-api-key"
            type="text"
            value={vultrKeyInput}
            onChange={(e) => setVultrKeyInput(e.target.value)}
            placeholder="Not configured"
            className="input-base"
            style={{ flex: 1, fontFamily: "'Share Tech Mono', monospace" }}
          />
          <button
            onClick={handleSaveVultrKey}
            disabled={savingVultrKey || vultrKeyInput === vultrKey}
            className="users-add-btn"
          >
            {savingVultrKey ? <Loader2 size={16} className="animate-spin" /> : null}
            <span>Save Vultr Key</span>
          </button>
        </div>
      </div>

      {/* Stats Hub target */}
      <div className="users-page-header" style={{ marginTop: '2rem' }}>
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <h2 className="users-page-title" style={{ fontSize: '20px' }}>Stats Hub</h2>
          </div>
        </div>
      </div>
      <div className="users-table-container">
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', padding: '16px 20px' }}>
          <p style={{ margin: 0, fontSize: '13px', opacity: 0.75 }}>
            The ql-stats-hub base URL and its STATS_HUB_INGEST_TOKEN (not the dashboard/read
            token) - used by every host's telemetry relay and to reserve a cluster-wide
            server_id per instance.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <label htmlFor="stats-hub-url" className="sr-only">Stats Hub URL</label>
            <input
              id="stats-hub-url"
              type="text"
              value={statsHubUrlInput}
              onChange={(e) => setStatsHubUrlInput(e.target.value)}
              placeholder="http://stats-hub-host:8090"
              className="input-base"
              style={{ flex: 1, fontFamily: "'Share Tech Mono', monospace" }}
            />
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <label htmlFor="stats-hub-token" className="sr-only">Stats Hub Ingest Token</label>
            <input
              id="stats-hub-token"
              type="text"
              value={statsHubTokenInput}
              onChange={(e) => setStatsHubTokenInput(e.target.value)}
              placeholder="STATS_HUB_INGEST_TOKEN"
              className="input-base"
              style={{ flex: 1, fontFamily: "'Share Tech Mono', monospace" }}
            />
            <button
              onClick={handleSaveStatsHub}
              disabled={savingStatsHub || (statsHubUrlInput === statsHubUrl && statsHubTokenInput === statsHubToken)}
              className="users-add-btn"
            >
              {savingStatsHub ? <Loader2 size={16} className="animate-spin" /> : null}
              <span>Save</span>
            </button>
          </div>
        </div>
      </div>

      <ConfirmationModal
        isOpen={showRevokeModal}
        onClose={() => setShowRevokeModal(false)}
        onConfirm={handleRevoke}
        title="Revoke API Key"
        message="Are you sure you want to revoke the API key? External services using this key will immediately lose access."
        confirmButtonText="Revoke"
        confirmButtonVariant="danger"
      />
    </div>
  );
}

export default SettingsPage;
