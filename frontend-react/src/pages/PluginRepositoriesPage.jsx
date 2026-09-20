import React, { useState, useEffect, useCallback } from 'react';
import {
  PackagePlus, AlertCircle, Loader2,
} from 'lucide-react';
import {
  getPluginRepositories,
  createPluginRepository,
  syncPluginRepository,
  deletePluginRepository,
  getPluginRepositoryUpdates,
} from '../services/api';
import { useNotification } from '../components/NotificationProvider';
import ConfirmationModal from '../components/ConfirmationModal';
import AddPluginRepositoryModal from '../components/pluginRepositories/AddPluginRepositoryModal';
import PluginRepositoryCard from '../components/pluginRepositories/PluginRepositoryCard';
import RestartQlsmBanner from '../components/system/RestartQlsmBanner';

function PluginRepositoriesPage() {
  const [repos, setRepos] = useState([]);
  const [updates, setUpdates] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedForDelete, setSelectedForDelete] = useState(null);
  const [syncingId, setSyncingId] = useState(null);
  // An addon installed from here is inert until qlsm restarts, same as one
  // uploaded on the Addons page.
  const [addonNeedsRestart, setAddonNeedsRestart] = useState(false);

  const { showSuccess, showError } = useNotification();

  // Local-vs-repo status per synced entry, keyed by repo id. Decoration on
  // top of the repo list: a failure here quietly renders no badges rather
  // than blocking the page.
  const fetchUpdates = useCallback(async () => {
    try {
      const data = await getPluginRepositoryUpdates();
      const byRepo = {};
      (data || []).forEach((entry) => {
        byRepo[entry.repo_id] = {
          plugins: Object.fromEntries((entry.plugins || []).map((p) => [p.filename, p.status])),
          addons: Object.fromEntries((entry.addons || []).map((a) => [a.id, a])),
        };
      });
      setUpdates(byRepo);
    } catch {
      setUpdates({});
    }
  }, []);

  // `silent` refreshes the list without flipping `loading`. The loading branch
  // replaces every card with a spinner, which unmounts them and throws away
  // card-local state -- including the overwrite confirm a partial download has
  // just raised, and any expanded card.
  const fetchRepos = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await getPluginRepositories();
      setRepos(data || []);
    } catch (err) {
      setError(err.error?.message || err.message || 'Failed to fetch plugin repositories.');
    } finally {
      if (!silent) setLoading(false);
    }
    fetchUpdates();
  }, [fetchUpdates]);

  useEffect(() => { fetchRepos(); }, [fetchRepos]);

  const handleCreateRepository = async (repoData) => {
    await createPluginRepository(repoData);
    showSuccess(`Repository "${repoData.name}" added.`);
    fetchRepos();
  };

  const handleSync = async (repo) => {
    setSyncingId(repo.id);
    try {
      await syncPluginRepository(repo.id);
      showSuccess(`Synced "${repo.name}".`);
    } catch (err) {
      showError(err.error?.message || err.message || `Failed to sync "${repo.name}".`);
    } finally {
      setSyncingId(null);
      fetchRepos();
    }
  };

  const handleDeleteRepository = async () => {
    if (!selectedForDelete) return;
    try {
      await deletePluginRepository(selectedForDelete.id);
      showSuccess(`Repository "${selectedForDelete.name}" deleted.`);
      fetchRepos();
    } catch (err) {
      showError(err.error?.message || err.message || 'Failed to delete repository.');
    }
    setIsDeleteModalOpen(false);
    setSelectedForDelete(null);
  };

  const openDeleteModal = (repo) => {
    setSelectedForDelete(repo);
    setIsDeleteModalOpen(true);
  };

  if (error) {
    return (
      <div className="users-page">
        <div className="users-page-header">
          <div className="users-page-title-row">
            <div className="users-page-title-wrapper">
              <PackagePlus className="users-page-title-icon" strokeWidth={2} />
              <h1 className="users-page-title">Repositories</h1>
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
      <div className="users-page-header">
        <div className="users-page-title-row">
          <div className="users-page-title-wrapper">
            <PackagePlus className="users-page-title-icon" strokeWidth={2} />
            <h1 className="users-page-title">Repositories</h1>
            {!loading && (
              <span className="users-page-count">{repos.length}</span>
            )}
          </div>
          <button onClick={() => setIsAddModalOpen(true)} className="users-add-btn">
            <PackagePlus size={18} strokeWidth={2} />
            <span>Add Repository</span>
          </button>
        </div>
        <p className="text-sm text-[var(--text-muted)] mt-2">
          External sources of minqlx plugins and qlsm addons. Downloading a plugin copies it into
          the operator tier of the local pool — it's picked up wherever that pool already is, no
          different from one qlsm ships itself. Installing an addon puts it on the addon packages
          volume, exactly like uploading its .zip on the Addons page.
        </p>
      </div>

      {addonNeedsRestart && (
        <RestartQlsmBanner message="An addon was installed. QLSM needs a restart before it takes effect." />
      )}

      {loading ? (
        <div className="users-loading-state">
          <Loader2 className="users-loading-spinner" strokeWidth={2} />
          <span className="users-loading-text">Loading repositories...</span>
        </div>
      ) : repos.length === 0 ? (
        <div className="users-empty-state">
          <PackagePlus size={32} strokeWidth={1.5} className="users-empty-icon" />
          <p className="users-empty-text">No repositories added yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {repos.map((repo) => (
            <PluginRepositoryCard
              key={repo.id}
              repo={repo}
              updates={updates[repo.id]}
              syncing={syncingId === repo.id}
              onSync={handleSync}
              onDelete={openDeleteModal}
              onDownloaded={() => fetchRepos({ silent: true })}
              onAddonInstalled={() => setAddonNeedsRestart(true)}
            />
          ))}
        </div>
      )}

      <AddPluginRepositoryModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSubmit={handleCreateRepository}
      />

      {selectedForDelete && (
        <ConfirmationModal
          isOpen={isDeleteModalOpen}
          onClose={() => {
            setIsDeleteModalOpen(false);
            setSelectedForDelete(null);
          }}
          onConfirm={handleDeleteRepository}
          title="Delete Repository"
          message={`Are you sure you want to remove "${selectedForDelete.name}"? Plugins already downloaded from it stay in the local pool, and installed addons stay installed.`}
          confirmButtonText="Delete"
          confirmButtonVariant="danger"
        />
      )}
    </div>
  );
}

export default PluginRepositoriesPage;
