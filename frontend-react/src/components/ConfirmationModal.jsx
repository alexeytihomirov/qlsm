import React from 'react';
import { AlertTriangle } from 'lucide-react';
import Modal from './Modal';

function ConfirmationModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmButtonText = 'Confirm',
  cancelButtonText = 'Cancel',
  confirmButtonVariant = 'danger',
  zIndexClass = 'z-10'
}) {
  const getConfirmButtonClasses = () => {
    const base = 'btn';
    switch (confirmButtonVariant) {
      case 'danger':
      case 'red':
        return `${base} btn-danger`;
      case 'primary':
        return `${base} btn-primary`;
      case 'amber':
      case 'warning':
        return `${base} bg-amber-500 dark:bg-[#FFB800] text-white dark:text-black font-semibold hover:bg-amber-600 dark:hover:bg-[#CC9300]`;
      case 'orange':
        return `${base} bg-orange-500 text-white font-semibold hover:bg-orange-600`;
      default:
        return `${base} btn-secondary`;
    }
  };

  const isDangerVariant = confirmButtonVariant === 'danger' || confirmButtonVariant === 'red';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      zIndexClass={zIndexClass}
      title={title}
      icon={isDangerVariant ? (
        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 dark:bg-[#FF3366]/10 border border-red-200 dark:border-[#FF3366]/30 flex items-center justify-center">
          <AlertTriangle className="w-5 h-5 text-red-600 dark:text-[#FF3366]" />
        </div>
      ) : null}
      footer={(
        <>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
          >
            {cancelButtonText}
          </button>
          <button
            type="button"
            className={getConfirmButtonClasses()}
            onClick={() => {
              onConfirm();
              onClose();
            }}
          >
            {confirmButtonText}
          </button>
        </>
      )}
    >
      <p className="text-sm text-theme-secondary">
        {message}
      </p>
    </Modal>
  );
}

export default ConfirmationModal;
