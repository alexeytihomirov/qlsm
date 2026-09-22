import React from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * Contains a crash inside one addon's UI.
 *
 * Required by the design (spec section 5.2): an addon's component runs inside
 * qlsm's own React tree, so without this a render error in a third-party
 * panel takes the whole page to a white screen. With it, the failure is a
 * labelled box in the addon's own slot and the rest of qlsm keeps working.
 *
 * A class component because React only supports error boundaries as classes.
 */
class AddonErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Named so the addon is identifiable in a browser console screenshot.
    console.error(`Addon "${this.props.addonId}" UI crashed:`, error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        className="rounded-lg border p-4 text-sm"
        style={{ borderColor: 'var(--accent-danger)', background: 'var(--surface-elevated)' }}
        role="alert"
      >
        <div className="flex items-center gap-2 font-medium" style={{ color: 'var(--accent-danger)' }}>
          <AlertTriangle size={15} />
          Addon "{this.props.addonId}" failed to render
        </div>
        <p className="mt-1 text-theme-secondary">
          The rest of QLSM is unaffected. Check the browser console for details.
        </p>
        <p className="mt-1 font-mono text-xs text-theme-muted break-all">
          {String(this.state.error?.message || this.state.error)}
        </p>
      </div>
    );
  }
}

export default AddonErrorBoundary;
