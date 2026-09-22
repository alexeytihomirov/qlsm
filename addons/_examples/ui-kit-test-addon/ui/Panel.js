// Pre-built ESM component (spec section 5.2). In a real addon this would come
// out of `vite build --lib` in the addon author's own project; written by
// hand here since the point of this addon is only to prove that an addon's
// own component can be built entirely out of window.__qlsm.ui and end up
// looking like a native part of QLSM -- with no Panel.css of its own. Every
// visual element below (the panel surface, the buttons, the inputs, the
// modal chrome) comes from the shared kit, which itself reuses core's own
// .card/.btn-*/modal-* CSS classes.
export default function Panel() {
  const React = window.__qlsm.react;
  const { useState } = React;
  const {
    Modal, Button, Panel: Card, AddonField, Icon, Stack, Row,
  } = window.__qlsm.ui;
  const h = React.createElement;

  const [modalOpen, setModalOpen] = useState(false);
  const [sampleText, setSampleText] = useState('');
  const [sampleChoice, setSampleChoice] = useState('alpha');

  return h(
    Stack,
    { gap: 4 },
    h(
      Card,
      null,
      h(
        Row,
        { gap: 2, className: 'mb-3' },
        h(Icon, { name: 'puzzle', className: 'text-theme-muted' }),
        h('h3', { className: 'font-display text-lg text-theme-primary' }, 'UI Kit Test Addon'),
      ),
      h(
        Stack,
        { gap: 1 },
        h(AddonField, {
          field: { key: 'sample_text', type: 'string', label: 'Sample text', placeholder: 'Type something' },
          value: sampleText,
          onChange: (_key, value) => setSampleText(value),
        }),
        h(AddonField, {
          field: {
            key: 'sample_choice',
            type: 'select',
            label: 'Sample choice',
            options: [
              { value: 'alpha', label: 'Alpha' },
              { value: 'beta', label: 'Beta' },
            ],
          },
          value: sampleChoice,
          onChange: (_key, value) => setSampleChoice(value),
        }),
      ),
      h(
        Row,
        { gap: 3, className: 'mt-4' },
        h(Button, { variant: 'primary', onClick: () => setModalOpen(true) }, 'Open modal'),
        h(Button, { variant: 'secondary' }, 'Secondary'),
        h(Button, { variant: 'danger' }, 'Danger'),
      ),
    ),
    h(
      Modal,
      {
        isOpen: modalOpen,
        onClose: () => setModalOpen(false),
        title: 'Generic modal',
        footer: h(Button, { variant: 'primary', onClick: () => setModalOpen(false) }, 'Close'),
      },
      h('p', { className: 'text-sm text-theme-secondary' },
        'Arbitrary content rendered through the shared Modal primitive, styled consistently with the rest of QLSM.'),
    ),
  );
}
