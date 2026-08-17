import { Zap } from 'lucide-react';
import InfoTooltip from '../common/InfoTooltip';

function InstanceOptionsRow({
  lanRateEnabled, onLanRateChange,
  lanRateDisabled = false,
  lanRateUnavailableReason = null,
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={() => onLanRateChange(!lanRateEnabled)}
        className="neu-toggle"
        aria-pressed={lanRateEnabled}
        disabled={lanRateDisabled}
      >
        <span className="sr-only">Toggle 99k LAN Rate</span>
        <span className={`neu-toggle__track ${lanRateEnabled ? 'neu-toggle__track--on' : 'neu-toggle__track--off'}`}>
          <span className={`neu-toggle__knob ${lanRateEnabled ? 'neu-toggle__knob--on' : 'neu-toggle__knob--off'}`} />
        </span>
      </button>
      <span className="flex items-center gap-1.5 text-sm font-medium text-[var(--text-primary)]">
        <Zap size={16} className={`mr-1 ${lanRateEnabled ? 'text-[var(--accent-warning)]' : 'text-[var(--text-muted)]'}`} />
        <span>99k LAN Rate</span>
        {lanRateUnavailableReason && (
          <InfoTooltip text={lanRateUnavailableReason} variant="danger" size={14} />
        )}
      </span>
    </div>
  );
}

export default InstanceOptionsRow;
