import { X, Check, AlertCircle } from 'lucide-react';
import { useState } from 'react';

interface Violation {
  id: string;
  rule_id?: string;
  rule_name?: string;
  metric?: string;
  message?: string;
  status?: string;
  instances_affected?: number;
  [key: string]: any;
}

interface ViolationsModalProps {
  violations: Violation[];
  onClose: () => void;
  onRepair: (selected: Violation[]) => void;
  isLoading?: boolean;
}

export function ViolationsModal({ violations, onClose, onRepair, isLoading }: ViolationsModalProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set(violations.map(v => v.id || v.rule_id)));

  const handleToggle = (violationId: string) => {
    const newSelected = new Set(selected);
    if (newSelected.has(violationId)) {
      newSelected.delete(violationId);
    } else {
      newSelected.add(violationId);
    }
    setSelected(newSelected);
  };

  const handleSelectAll = () => {
    if (selected.size === violations.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(violations.map(v => v.id || v.rule_id)));
    }
  };

  const selectedViolations = violations.filter(v => selected.has(v.id || v.rule_id));

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title">
            <AlertCircle size={20} />
            <span>Select Issues to Fix</span>
          </div>
          <button className="modal-close" onClick={onClose} disabled={isLoading}>
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div className="modal-body">
          <p className="modal-subtitle">
            {violations.length} issue{violations.length !== 1 ? 's' : ''} found. Select which ones to fix:
          </p>

          {/* Select All */}
          <div className="modal-select-all">
            <label>
              <input
                type="checkbox"
                checked={selected.size === violations.length && violations.length > 0}
                onChange={handleSelectAll}
                disabled={isLoading}
              />
              <span>{selected.size === violations.length ? 'Deselect all' : 'Select all'}</span>
            </label>
          </div>

          {/* Violations List */}
          <div className="modal-violations-list">
            {violations.map(v => {
              const violationId = v.id || v.rule_id;
              const isChecked = selected.has(violationId);

              return (
                <label key={violationId} className="modal-violation-item">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => handleToggle(violationId)}
                    disabled={isLoading}
                  />
                  <div className="violation-info">
                    <strong>{v.rule_name || v.metric || violationId}</strong>
                    <p>{v.message}</p>
                    {v.instances_affected && (
                      <small className="violation-instances">
                        Affects {v.instances_affected} instance{v.instances_affected !== 1 ? 's' : ''}
                      </small>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button className="modal-button-secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </button>
          <button
            className="modal-button-primary"
            onClick={() => onRepair(selectedViolations)}
            disabled={!selectedViolations.length || isLoading}
          >
            {isLoading ? (
              <>
                <span className="spinner" />
                Fixing...
              </>
            ) : (
              <>
                <Check size={16} />
                Fix {selectedViolations.length} Issue{selectedViolations.length !== 1 ? 's' : ''}
              </>
            )}
          </button>
        </div>
      </div>

      <style>{`
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.4);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
        }

        .modal-content {
          background: white;
          border-radius: 12px;
          box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
          width: 90%;
          max-width: 500px;
          max-height: 80vh;
          display: flex;
          flex-direction: column;
          animation: slideUp 0.2s ease-out;
        }

        @keyframes slideUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .modal-header {
          padding: 20px;
          border-bottom: 1px solid #e5e7eb;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .modal-title {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 18px;
          font-weight: 600;
          color: #1f2937;
        }

        .modal-close {
          background: none;
          border: none;
          cursor: pointer;
          padding: 4px;
          color: #6b7280;
          display: flex;
          align-items: center;
          transition: color 0.2s;
        }

        .modal-close:hover:not(:disabled) {
          color: #1f2937;
        }

        .modal-close:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .modal-body {
          flex: 1;
          overflow-y: auto;
          padding: 20px;
        }

        .modal-subtitle {
          font-size: 14px;
          color: #6b7280;
          margin-bottom: 15px;
        }

        .modal-select-all {
          margin-bottom: 15px;
          padding-bottom: 15px;
          border-bottom: 1px solid #f3f4f6;
        }

        .modal-select-all label {
          display: flex;
          align-items: center;
          gap: 10px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
        }

        .modal-select-all input[type="checkbox"] {
          cursor: pointer;
        }

        .modal-violations-list {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .modal-violation-item {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 12px;
          border-radius: 8px;
          border: 1px solid #e5e7eb;
          cursor: pointer;
          transition: all 0.2s;
        }

        .modal-violation-item:hover {
          background: #f9fafb;
          border-color: #d1d5db;
        }

        .modal-violation-item input[type="checkbox"] {
          margin-top: 2px;
          cursor: pointer;
        }

        .violation-info {
          flex: 1;
        }

        .violation-info strong {
          display: block;
          color: #1f2937;
          font-size: 14px;
          margin-bottom: 4px;
        }

        .violation-info p {
          color: #6b7280;
          font-size: 13px;
          margin: 0;
        }

        .violation-instances {
          display: block;
          color: #9ca3af;
          font-size: 12px;
          margin-top: 4px;
        }

        .modal-footer {
          padding: 15px 20px;
          border-top: 1px solid #e5e7eb;
          display: flex;
          gap: 10px;
          justify-content: flex-end;
        }

        .modal-button-primary,
        .modal-button-secondary {
          padding: 10px 16px;
          border-radius: 8px;
          border: none;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 8px;
          transition: all 0.2s;
        }

        .modal-button-primary {
          background: #2563eb;
          color: white;
        }

        .modal-button-primary:hover:not(:disabled) {
          background: #1d4ed8;
        }

        .modal-button-primary:disabled {
          background: #bfdbfe;
          cursor: not-allowed;
        }

        .modal-button-secondary {
          background: #f3f4f6;
          color: #374151;
        }

        .modal-button-secondary:hover:not(:disabled) {
          background: #e5e7eb;
        }

        .modal-button-secondary:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .spinner {
          display: inline-block;
          width: 14px;
          height: 14px;
          border: 2px solid #ffffff;
          border-top-color: transparent;
          border-radius: 50%;
          animation: spin 0.6s linear infinite;
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </div>
  );
}
