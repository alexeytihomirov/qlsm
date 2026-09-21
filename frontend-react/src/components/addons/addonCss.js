import { addonAssetUrl } from '../../services/addons';

/**
 * An addon's CSS is discovered by convention, not declared in the manifest:
 * if `ui/Panel.js` has a `ui/Panel.css` next to it, it gets loaded. No addon
 * ships CSS today, so a manifest field would be speculative; the convention
 * costs an addon author nothing extra and needs no schema change.
 */
export function addonCssPathFor(component) {
  return typeof component === 'string' && component.toLowerCase().endsWith('.js')
    ? `${component.slice(0, -3)}.css`
    : null;
}

/**
 * Injects a <link rel="stylesheet"> for the addon's CSS, if any. Left in
 * document.head for the page's lifetime rather than removed on unmount --
 * CSS is idempotent, and a mount point that gets toggled (e.g. switching
 * tabs back and forth) shouldn't refetch and reapply it every time. Keyed by
 * addon id + path so the same stylesheet is never linked twice.
 */
export function ensureAddonCss(addonId, component) {
  if (typeof document === 'undefined') return;
  const cssPath = addonCssPathFor(component);
  if (!cssPath) return;
  const linkId = `qlsm-addon-css--${addonId}--${cssPath}`;
  if (document.getElementById(linkId)) return;
  const link = document.createElement('link');
  link.id = linkId;
  link.rel = 'stylesheet';
  link.href = addonAssetUrl(addonId, cssPath);
  // No CSS next to this component is the common case, not an error -- drop
  // the tag quietly instead of leaving a permanently-failed request in head.
  link.onerror = () => link.remove();
  document.head.appendChild(link);
}
