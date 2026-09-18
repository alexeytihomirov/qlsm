// Pre-built ESM component (spec section 5.2). In a real addon this would come
// out of `vite build --lib` in the addon author's own project; written by
// hand here since the point of this addon is only to prove Panel.css next to
// this file gets loaded by AddonComponentHost -- see qlsm-addon-css-loading
// in docs/superpowers/specs for the decision this addon demonstrates.
export default function Panel({ ctx }) {
  const React = window.__qlsm.react;
  return React.createElement(
    'div',
    { className: 'css-test-addon-panel' },
    React.createElement('h3', null, 'CSS Test Addon'),
    React.createElement(
      'p',
      null,
      'If this box has a pink border and dark background, Panel.css loaded correctly.',
    ),
  );
}
