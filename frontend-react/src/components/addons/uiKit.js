// The shared UI surface an addon's own component may use.
//
// Deliberately a small, explicit allow-list rather than "export everything":
// every symbol here becomes a compatibility promise to already-built addon
// bundles, and a promise is much easier to add later than to withdraw.
//
// Bumping what a bundle can rely on means bumping CURRENT_UI_API in
// ui/addons/manifest.py so an older core refuses to mount a newer addon
// instead of failing at runtime.
export { default as ConfirmationModal } from '../ConfirmationModal';
export { default as StatusIndicator } from '../StatusIndicator';
export { default as AddonField } from './AddonField';
export { useNotification } from '../NotificationProvider';

// CodeMirrorEditor is deliberately NOT here yet. This module sits in the
// import chain of every action menu (AddonPanel -> AddonComponentHost ->
// uiKit), and CodeMirror does real work at module load: exporting it eagerly
// dragged the whole editor into unrelated components and broke their tests,
// while exporting it lazily made it both statically and dynamically imported
// and produced a new build warning for no benefit (the app is one chunk).
// If an addon ever needs an editor, add it behind a CURRENT_UI_API bump.
