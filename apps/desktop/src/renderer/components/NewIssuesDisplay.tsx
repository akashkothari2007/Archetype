import { AlertCircle, Check, AlertTriangle, Info } from 'lucide-react';

interface Issue {
  id?: string;
  rule_id?: string;
  rule_name?: string;
  metric?: string;
  message?: string;
  [key: string]: any;
}

interface NewIssuesDisplayProps {
  newIssuesFound: Issue[];
  fixedNewIssues: Issue[];
  unfixedNewIssues: Issue[];
  llmCallsMade: number;
  onFixRemaining?: () => void;
  isLoading?: boolean;
}

export function NewIssuesDisplay({
  newIssuesFound,
  fixedNewIssues,
  unfixedNewIssues,
  llmCallsMade,
  onFixRemaining,
  isLoading,
}: NewIssuesDisplayProps) {
  if (!newIssuesFound || newIssuesFound.length === 0) {
    return null;
  }

  return (
    <div className="new-issues-container">
      <div className="new-issues-header">
        <AlertCircle size={18} className="icon-warning" />
        <h4>New Issues Detected</h4>
        <span className="issue-count">{newIssuesFound.length}</span>
      </div>

      <p className="new-issues-summary">
        {newIssuesFound.length} new issue{newIssuesFound.length !== 1 ? 's' : ''} appeared during your edits.
        {fixedNewIssues.length > 0 && ` ${fixedNewIssues.length} was${fixedNewIssues.length !== 1 ? 'were' : ''} fixed.`}
      </p>

      {/* Fixed Issues */}
      {fixedNewIssues.length > 0 && (
        <div className="issues-section">
          <div className="issues-section-header success">
            <Check size={16} />
            <span>Fixed ({fixedNewIssues.length})</span>
          </div>
          <div className="issues-list">
            {fixedNewIssues.map(issue => (
              <div key={issue.id || issue.rule_id} className="issue-item fixed">
                <Check size={14} className="issue-icon" />
                <div className="issue-content">
                  <strong>{issue.rule_name || issue.metric || issue.rule_id}</strong>
                  <p>{issue.message}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Unfixed Issues */}
      {unfixedNewIssues.length > 0 && (
        <div className="issues-section">
          <div className="issues-section-header warning">
            <AlertTriangle size={16} />
            <span>Still Need Attention ({unfixedNewIssues.length})</span>
          </div>
          <div className="issues-list">
            {unfixedNewIssues.map(issue => (
              <div key={issue.id || issue.rule_id} className="issue-item unfixed">
                <AlertTriangle size={14} className="issue-icon" />
                <div className="issue-content">
                  <strong>{issue.rule_name || issue.metric || issue.rule_id}</strong>
                  <p>{issue.message}</p>
                </div>
              </div>
            ))}
          </div>
          {onFixRemaining && (
            <button
              className="fix-remaining-button"
              onClick={onFixRemaining}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <span className="spinner" />
                  Fixing...
                </>
              ) : (
                <>
                  <AlertTriangle size={14} />
                  Fix Remaining Issue{unfixedNewIssues.length !== 1 ? 's' : ''}
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Info */}
      <div className="new-issues-meta">
        <Info size={14} />
        <small>LLM calls used: {llmCallsMade}</small>
      </div>

      <style>{`
        .new-issues-container {
          margin-top: 16px;
          padding: 14px;
          background: #fef3c7;
          border: 1px solid #fcd34d;
          border-radius: 8px;
        }

        .new-issues-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
        }

        .new-issues-header h4 {
          margin: 0;
          font-size: 14px;
          font-weight: 600;
          color: #92400e;
          flex: 1;
        }

        .icon-warning {
          color: #d97706;
        }

        .issue-count {
          background: #f59e0b;
          color: white;
          padding: 2px 8px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 600;
        }

        .new-issues-summary {
          font-size: 13px;
          color: #78350f;
          margin: 0 0 12px 0;
        }

        .issues-section {
          margin-bottom: 12px;
        }

        .issues-section-header {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 12px;
          font-weight: 600;
          padding-bottom: 8px;
          margin-bottom: 8px;
          border-bottom: 1px solid #fde68a;
        }

        .issues-section-header.success {
          color: #059669;
        }

        .issues-section-header.warning {
          color: #d97706;
        }

        .issues-list {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .issue-item {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          padding: 8px;
          background: white;
          border-radius: 6px;
          border-left: 3px solid;
        }

        .issue-item.fixed {
          border-left-color: #10b981;
        }

        .issue-item.unfixed {
          border-left-color: #f97316;
        }

        .issue-icon {
          margin-top: 1px;
          flex-shrink: 0;
        }

        .issue-item.fixed .issue-icon {
          color: #10b981;
        }

        .issue-item.unfixed .issue-icon {
          color: #f97316;
        }

        .issue-content {
          flex: 1;
        }

        .issue-content strong {
          display: block;
          font-size: 12px;
          color: #1f2937;
          margin-bottom: 2px;
        }

        .issue-content p {
          font-size: 11px;
          color: #6b7280;
          margin: 0;
        }

        .fix-remaining-button {
          width: 100%;
          margin-top: 10px;
          padding: 8px 12px;
          background: #f97316;
          color: white;
          border: none;
          border-radius: 6px;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          transition: all 0.2s;
        }

        .fix-remaining-button:hover:not(:disabled) {
          background: #ea580c;
        }

        .fix-remaining-button:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }

        .spinner {
          display: inline-block;
          width: 12px;
          height: 12px;
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

        .new-issues-meta {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-top: 10px;
          padding-top: 10px;
          border-top: 1px solid #fde68a;
          color: #92400e;
          font-size: 11px;
        }
      `}</style>
    </div>
  );
}
