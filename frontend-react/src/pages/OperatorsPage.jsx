import React, { useState, useEffect, useCallback } from 'react';
import { UserPlus, Trash2, ShieldCheck, AlertCircle, Loader2 } from 'lucide-react';
import { getOperators, createOperator, deleteOperator } from '../services/api';
import { useNotification } from '../components/NotificationProvider';
import ConfirmationModal from '../components/ConfirmationModal';
import AddOperatorModal from '../components/operators/AddOperatorModal';
import { formatDateTime } from '../utils/uiUtils';

function OperatorsPage() {
  const [operators, setOperators] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [selectedForDelete, setSelectedForDelete] = useState(null);

  const { showSuccess, showError } = useNotification();

  const fetchOperators = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getOperators();
      setOperators(data || []);
    } catch (err) {
      setError(err.error?.message || err.message || 'Failed to fetch operators.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchOperators(); }, [fetchOperators]);

  const handleCreateOperator = async (operatorData) => {
    await createOperator(operatorData);
    showSuccess(`Operator "${operatorData.name}" added successfully.`);
    fetchOperators();
  };

  const handleDeleteOperator = async () => {
    if (!selectedForDelete) return;
    try {
      await deleteOperator(selectedForDelete.id);
      showSuccess(`Operator "${selectedForDelete.name}" deleted successfully.`);
      fetchOperators();
    } catch (err) {
      showError(err.error?.message || err.message || 'Failed to delete operator.');
    }
    setIsDeleteModalOpen(false);
    setSelectedForDelete(null);
  };

  const openDeleteModal = (operator) => {
    setSelectedForDelete(operator);
    setIsDeleteModalOpen(true);
  };

  if (error) {
    return (
      <div className="users-page">
        <div className="users-page-header">
          <div className="users-page-title-row">
            <div className="users-page-title-wrapper">
              <ShieldCheck className="users-page-title-icon" strokeWidth={2} />
              <h1 className="users-page-title">Operators</h1>
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
            <ShieldCheck className="users-page-title-icon" strokeWidth={2} />
            <h1 className="users-page-title">Operators</h1>
            {!loading && (
              <span className="users-page-count">{operators.length}</span>
            )}
          </div>
          <button onClick={() => setIsAddModalOpen(true)} className="users-add-btn">
            <UserPlus size={18} strokeWidth={2} />
            <span>Add Operator</span>
          </button>
        </div>
        <p className="text-sm text-[var(--text-muted)] mt-2">
          Operators added here can be assigned as Owner or Admin when editing an instance,
          preset, or new-instance server config.
        </p>
      </div>

      {loading ? (
        <div className="users-loading-state">
          <Loader2 className="users-loading-spinner" strokeWidth={2} />
          <span className="users-loading-text">Loading operators...</span>
        </div>
      ) : operators.length === 0 ? (
        <div className="users-empty-state">
          <ShieldCheck size={32} strokeWidth={1.5} className="users-empty-icon" />
          <p className="users-empty-text">No operators found.</p>
        </div>
      ) : (
        <div className="users-table-container">
          <table className="users-table">
            <thead>
              <tr>
                <th className="users-th">Name</th>
                <th className="users-th">SteamID64</th>
                <th className="users-th">Default Level</th>
                <th className="users-th">Added</th>
                <th className="users-th users-th-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {operators.map((operator) => (
                <tr key={operator.id} className="users-tr">
                  <td className="users-td">
                    <span className="users-td-username">{operator.name}</span>
                  </td>
                  <td className="users-td">
                    <span className="font-mono text-sm">{operator.steam_id64}</span>
                  </td>
                  <td className="users-td">
                    <span>{operator.default_level}</span>
                  </td>
                  <td className="users-td">
                    <span className="users-td-date">{formatDateTime(operator.created_at)}</span>
                  </td>
                  <td className="users-td users-td-actions">
                    <button
                      onClick={() => openDeleteModal(operator)}
                      className="users-action-btn users-action-btn-delete"
                      title="Delete Operator"
                    >
                      <Trash2 size={16} strokeWidth={2} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <AddOperatorModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSubmit={handleCreateOperator}
      />

      {selectedForDelete && (
        <ConfirmationModal
          isOpen={isDeleteModalOpen}
          onClose={() => {
            setIsDeleteModalOpen(false);
            setSelectedForDelete(null);
          }}
          onConfirm={handleDeleteOperator}
          title="Delete Operator"
          message={`Are you sure you want to delete operator "${selectedForDelete.name}"? This does not remove them from any server.cfg / access.txt they were already added to.`}
          confirmButtonText="Delete"
          confirmButtonVariant="danger"
        />
      )}
    </div>
  );
}

export default OperatorsPage;
