import { useCallback, useRef, useState } from 'react';

// Tracks whether any of several file managers has an upload batch running, so the
// owning form can hold Save until the files have landed in what Save serializes.
export function useUploadBusy() {
  const [busy, setBusy] = useState({});
  const handlersRef = useRef({});
  const track = useCallback((key) => {
    if (!handlersRef.current[key]) {
      handlersRef.current[key] = (isBusy) =>
        setBusy((prev) => (prev[key] === isBusy ? prev : { ...prev, [key]: isBusy }));
    }
    return handlersRef.current[key];
  }, []);
  return { uploading: Object.values(busy).some(Boolean), track };
}
