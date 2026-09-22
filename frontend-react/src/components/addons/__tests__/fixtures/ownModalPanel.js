// Stands in for a real tier-2 addon bundle: plain ESM, a default export, and
// React taken off window.__qlsm rather than imported (see addons/README.md).
// Deliberately not a .jsx file compiled by this project's build -- the point
// of the test that loads it is that AddonComponentHost can mount something it
// fetched at runtime by URL, not something bundled with core.
export default function Panel({ ctx }) {
  const React = window.__qlsm.react;
  const h = React.createElement;
  const modal = ctx.modal;

  // Parked for the test to inspect: a real addon would just use these.
  window.__lastAddonCtx = ctx;

  return h(
    'div',
    null,
    h('p', null, `entity:${modal ? modal.entity?.name : 'none'}`),
    h('p', null, `open:${modal ? String(modal.isOpen) : 'none'}`),
    h('p', null, `handles:${['api', 'apiFor', 'download', 'saveBlob']
      .filter((k) => typeof ctx[k] === 'function').join(',')}`),
    h('button', { type: 'button', onClick: () => modal.onClose() }, 'Close'),
  );
}
