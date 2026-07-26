import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, ChevronUp, Copy } from 'lucide-react';

import { useNotification } from '../NotificationProvider';
import { copyToClipboard } from '../../utils/clipboard';
import {
  RCON_CONTENT_PADDING, RCON_FONT_FAMILY, RCON_FONT_SIZE, RCON_FRAME_CLASS,
  RCON_GUTTER, RCON_LINE_HEIGHT, RCON_SURFACE_BACKGROUND, RCON_TEXT_COLOR,
} from '../../utils/rconTheme';
import QuakeColoredText, { QuakeEventText } from './QuakeColoredText';
import RconRawOutputViewer from './RconRawOutputViewer';
import useIncrementalViewerReplay from './useIncrementalViewerReplay';

const LABELS = {
  pending_dispatch: 'Dispatching',
  queued: 'Queued',
  receiving: 'Receiving',
  no_response: 'No response yet',
  skipped: 'Skipped',
  rejected: 'Rejected',
  failed: 'Failed',
};

// A fleet-wide command answers from every selected server at once, so each
// target block collapses down to a single preview line. Anything longer than
// that is expandable rather than shown inline.
const PREVIEW_LINES = 1;

function physicalLines(lines = []) {
  return lines.flatMap((line) => String(line.content ?? '').split('\n'));
}

function statusText(result) {
  const label = LABELS[result.state] ?? result.state;
  return result.reason ? `${label}: ${result.reason}` : label;
}

function isDefaultExpanded(result) {
  return result.state === 'failed' || (result.lines ?? []).some((line) => line.type === 'error');
}

function OutputViewer({ events, lineCount, resultKey }) {
  const viewerRef = useRef(null);
  useIncrementalViewerReplay(viewerRef, events, resultKey);

  const height = Math.min(360, Math.max(96, lineCount * 22 + 48));
  return (
    <div className="mt-2" style={{ height }}>
      <RconRawOutputViewer ref={viewerRef} showMetadata={false} />
    </div>
  );
}

// Collapsed output keeps the viewer's rectangle rather than falling back to
// naked text: same frame, fill, gutter and font metrics, just one line of it.
// CodeMirror stays unmounted — a run holds a block per target, so the static
// replica is what makes the collapsed state cheap in the first place.
// Truncated rather than wrapped: a long line would otherwise flow onto a
// second row that the max-height cap clips through the middle.
function CollapsedLine({ line }) {
  return (
    <div className={`mt-2 flex ${RCON_FRAME_CLASS}`} style={{ background: RCON_SURFACE_BACKGROUND }}>
      <span aria-hidden="true" className="flex-none select-none text-right" style={{
        ...RCON_GUTTER, fontFamily: RCON_FONT_FAMILY, fontSize: RCON_FONT_SIZE, lineHeight: RCON_LINE_HEIGHT,
      }}>1</span>
      <QuakeColoredText
        singleLine
        text={String(line?.content ?? '').split('\n')[0]}
        error={line?.type === 'error'}
        className="min-w-0 flex-1"
        style={{
          fontFamily: RCON_FONT_FAMILY, fontSize: RCON_FONT_SIZE, lineHeight: RCON_LINE_HEIGHT,
          padding: RCON_CONTENT_PADDING, color: RCON_TEXT_COLOR,
        }}
      />
    </div>
  );
}

function ResultOutput({ result, expanded, onExpandedChange, onFilterChange }) {
  const { addNotification } = useNotification();
  const [searching, setSearching] = useState(false);
  const [copied, setCopied] = useState(false);
  const lines = result.lines ?? [];
  const flattened = physicalLines(lines);
  const count = flattened.length;
  const defaultExpanded = isDefaultExpanded(result);
  const expandable = count > PREVIEW_LINES;
  const showAll = !expandable || (expanded ?? defaultExpanded);
  const tone = ['failed', 'rejected'].includes(result.state) ? 'border-red-500/40 bg-red-500/5'
    : result.state === 'skipped' ? 'border-amber-500/40 bg-amber-500/5'
      : 'border-theme bg-theme-elevated';
  const countLabel = `${count} ${count === 1 ? 'line' : 'lines'}`;

  // Swapping straight to the one-line preview on collapse leaves the box
  // shorter than max-height at every point of the transition, so there's
  // nothing left for max-height to clip and the collapse looks instant.
  // Keep the full viewer mounted until the collapse transition finishes so
  // it has real height to animate down, then swap to the light preview.
  const [renderFull, setRenderFull] = useState(showAll);
  // While streaming, a result starts with <=5 lines (not expandable, so
  // showAll is forced true and the full viewer renders directly with no
  // transition div at all). Once it crosses 5 lines, the animated div is
  // born already collapsed — nothing was ever visibly open to animate down
  // from, so no transitionend will ever fire. Snap straight to the light
  // preview in that case instead of leaving the viewer stuck clipped.
  const wasExpandableRef = useRef(expandable);
  if (!showAll && renderFull && !wasExpandableRef.current) setRenderFull(false);
  useEffect(() => {
    wasExpandableRef.current = expandable;
    if (showAll) setRenderFull(true);
  }, [showAll, expandable]);

  // Same copy affordance as the IP address column on the Servers page:
  // icon swaps to a check for 2s and a toast confirms the copy.
  const handleCopy = () => {
    copyToClipboard(flattened.join('\n')).then(() => {
      setCopied(true);
      addNotification('Output copied to clipboard', 'success');
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  };

  return (
    <section className={`rounded-md border p-3 ${tone}`} aria-label={`${result.name} output`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-left text-sm">
          {/* Same chevron affordance as the Servers page host row: shared
              .expand-icon rotation/easing, muted tone, points right when
              collapsed and down when open. Non-expandable results keep an
              equal-width spacer so every target name stays on one gutter. */}
          {expandable ? (
            <button
              type="button"
              aria-label={`${showAll ? 'Collapse' : 'Expand'} output for ${result.name}`}
              aria-expanded={showAll}
              onClick={() => onExpandedChange(!showAll)}
              className="flex h-5 w-5 flex-none items-center justify-center rounded text-theme-muted hover:bg-black/10 dark:hover:bg-white/10"
            >
              <span className={`expand-icon${showAll ? ' is-expanded' : ''}`}>
                <ChevronRight size={16} />
              </span>
            </button>
          ) : <span className="h-5 w-5 flex-none" aria-hidden="true" />}
          {onFilterChange ? (
            <button
              type="button"
              aria-label={`Show raw output for ${result.name}`}
              onClick={() => onFilterChange(result.key)}
              className="font-medium text-theme-primary underline"
            >
              {result.name}
            </button>
          ) : <span className="font-medium text-theme-primary">{result.name}</span>}
          <button
            type="button"
            aria-label={`${result.name}, ${countLabel}`}
            aria-expanded={showAll}
            onClick={() => expandable && onExpandedChange(!showAll)}
            className="text-xs text-theme-muted"
          >
            {countLabel}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {result.state !== 'quiet' && (
            <span className="text-xs text-theme-muted" role="status">{statusText(result)}</span>
          )}
          {!expandable && count > 0 && (searching ? (
            <button type="button" aria-label={`Close output search for ${result.name}`}
              onClick={() => setSearching(false)} className="text-xs text-theme-secondary underline">
              Close search
            </button>
          ) : (
            <button type="button" aria-label={`Search output for ${result.name}`}
              onClick={() => setSearching(true)} className="text-xs text-theme-secondary underline">
              Search
            </button>
          ))}
          <button type="button" aria-label={`Copy output for ${result.name}`}
            onClick={handleCopy}
            className="p-1 text-theme-muted hover:text-theme-secondary rounded transition-colors hover:bg-black/5 dark:hover:bg-white/5">
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
        </div>
      </div>
      {count > 0 && (expandable ? (
        // Same reveal animation as the Targets tree's host expand/collapse
        // and the Servers page's instance list: a generous max-height cap
        // that transitions instead of snapping between the one-line preview
        // and the full viewer.
        // The collapsed cap is the framed one-liner's exact height (8px top
        // margin + 2px borders + 8px padding either side of a 21.6px line),
        // so the mid-collapse viewer clips to the same rectangle the replica
        // then takes over — the swap is invisible.
        <div className={`overflow-hidden transition-[max-height] ${showAll
          ? 'max-h-[420px] duration-[450ms] ease-in' : 'max-h-[52px] duration-300 ease-out'}`}
          onTransitionEnd={(event) => {
            if (event.target === event.currentTarget && event.propertyName === 'max-height' && !showAll) {
              setRenderFull(false);
            }
          }}>
          {renderFull
            ? <OutputViewer events={lines} lineCount={count} resultKey={result.key} />
            : <CollapsedLine line={lines[0]} />}
        </div>
      ) : (searching
        ? <OutputViewer events={lines} lineCount={count} resultKey={result.key} />
        : <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-sm text-theme-primary">
            <QuakeEventText events={lines} />
          </pre>))}
      {result.ack_anomaly && (
        <p className="mt-2 text-xs font-medium text-amber-600 dark:text-amber-400">
          Dispatch rejected after output was received.
        </p>
      )}
    </section>
  );
}

export default function RconCommandRun({ run, onFilterChange }) {
  const [expandedByKey, setExpandedByKey] = useState({});
  const results = run.results ?? [];
  const expandableResults = results.filter(
    (result) => physicalLines(result.lines).length > PREVIEW_LINES,
  );
  const setExpanded = (key, expanded) => {
    setExpandedByKey((current) => ({ ...current, [key]: expanded }));
  };
  const setAllExpanded = (expanded) => {
    setExpandedByKey((current) => {
      const next = { ...current };
      for (const result of expandableResults) next[result.key] = expanded;
      return next;
    });
  };
  const allExpanded = expandableResults.length > 0 && expandableResults.every(
    (result) => expandedByKey[result.key] ?? isDefaultExpanded(result),
  );
  const targetCount = results.length;

  return (
    <article className="rounded-lg border border-theme bg-theme-base p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono font-semibold text-theme-primary">&gt; {run.command}</h3>
        <span className="text-xs text-theme-muted">
          {run.timestamp} · {targetCount} {targetCount === 1 ? 'target' : 'targets'}
        </span>
      </header>
      {expandableResults.length > 0 && (
        <div className="mb-2 flex justify-end">
          <button type="button" aria-label={allExpanded ? 'Collapse all target output' : 'Expand all target output'}
            onClick={() => setAllExpanded(!allExpanded)} className="btn btn-secondary gap-1.5">
            {allExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {allExpanded ? 'Collapse All' : 'Expand All'}
          </button>
        </div>
      )}
      <div className="space-y-2">
        {results.map((result) => (
          <ResultOutput
            key={result.key}
            result={result}
            expanded={expandedByKey[result.key]}
            onExpandedChange={(expanded) => setExpanded(result.key, expanded)}
            onFilterChange={onFilterChange}
          />
        ))}
      </div>
    </article>
  );
}
