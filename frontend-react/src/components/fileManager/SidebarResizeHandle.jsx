// Drag handle sitting between the file-list sidebar and the editor pane. It
// draws the 1px divider the sidebar used to own as `border-r`, and widens its
// grab area with an invisible overlay so it isn't a pixel hunt.

import { useEffect, useRef, useState } from 'react';

import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  setSidebarWidth,
  useSidebarWidth,
} from './useSidebarWidth';

const KEYBOARD_STEP = 16;

export default function SidebarResizeHandle() {
  const width = useSidebarWidth();
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef(null);

  // Suppress text selection for the whole drag — without this, dragging left
  // across the tree highlights every filename it crosses.
  useEffect(() => {
    if (!dragging) return undefined;
    const { body } = document;
    const previousUserSelect = body.style.userSelect;
    const previousCursor = body.style.cursor;
    body.style.userSelect = 'none';
    body.style.cursor = 'col-resize';
    return () => {
      body.style.userSelect = previousUserSelect;
      body.style.cursor = previousCursor;
    };
  }, [dragging]);

  const handlePointerDown = (e) => {
    if (e.button) return;
    dragRef.current = { pointerId: e.pointerId, startX: e.clientX, startWidth: width };
    // Pointer capture keeps move/up events coming here once the cursor leaves
    // the 1px divider, which it does immediately on any real drag.
    e.currentTarget.setPointerCapture?.(e.pointerId);
    setDragging(true);
  };

  const handlePointerMove = (e) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    setSidebarWidth(drag.startWidth + (e.clientX - drag.startX));
  };

  const endDrag = (e) => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    if (e.currentTarget.hasPointerCapture?.(drag.pointerId)) {
      e.currentTarget.releasePointerCapture?.(drag.pointerId);
    }
    setDragging(false);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setSidebarWidth(width - KEYBOARD_STEP);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setSidebarWidth(width + KEYBOARD_STEP);
    } else if (e.key === 'Home') {
      // Keyboard equivalent of double-clicking the handle.
      e.preventDefault();
      setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
    }
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize file list"
      aria-valuenow={width}
      aria-valuemin={MIN_SIDEBAR_WIDTH}
      aria-valuemax={MAX_SIDEBAR_WIDTH}
      tabIndex={0}
      data-testid="sidebar-resize-handle"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={() => setSidebarWidth(DEFAULT_SIDEBAR_WIDTH)}
      onKeyDown={handleKeyDown}
      className={`group relative w-px flex-shrink-0 cursor-col-resize touch-none transition-colors focus:outline-none focus-visible:bg-[var(--accent-primary)] ${
        dragging
          ? 'bg-[var(--accent-primary)]'
          : 'bg-[var(--surface-border)] hover:bg-[var(--accent-primary)]'
      }`}
    >
      <span className="absolute inset-y-0 -left-1.5 -right-1.5" aria-hidden="true" />
      <span
        aria-hidden="true"
        className={`pointer-events-none absolute top-1/2 left-1/2 flex h-12 w-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border transition-colors ${
          dragging
            ? 'border-[var(--accent-primary)] bg-[#3a3b42]'
            : 'border-[#3c4453] bg-[#2a2b30] group-hover:border-[var(--accent-primary)] group-hover:bg-[#3a3b42]'
        }`}
        style={{ boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4)' }}
      >
        <svg viewBox="0 0 16 16" width="12" height="12" className="text-[#e2e8f0]">
          <rect x="4" y="2" width="2" height="12" rx="1" fill="currentColor" />
          <rect x="10" y="2" width="2" height="12" rx="1" fill="currentColor" />
        </svg>
      </span>
    </div>
  );
}
