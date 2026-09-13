import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi, beforeEach } from 'vitest';
import OwnerAdminEditor from '../OwnerAdminEditor';

const getOperators = vi.fn();
const getInstanceAdmins = vi.fn();
const createOperator = vi.fn();
vi.mock('../../../services/api', () => ({
  getOperators: (...a) => getOperators(...a),
  createOperator: (...a) => createOperator(...a),
  getInstanceAdmins: (...a) => getInstanceAdmins(...a),
}));

beforeEach(() => {
  getOperators.mockReset().mockResolvedValue([{ id: 1, name: 'Vex', steam_id64: '76561198012345678', default_level: 5 }]);
  getInstanceAdmins.mockReset().mockResolvedValue({ admins: [], error: null });
  createOperator.mockReset().mockResolvedValue({});
});

const base = {
  serverCfgContent: '',
  onServerCfgChange: () => {},
  instanceId: 1,
  adminEntries: null,
  onAdminEntriesChange: () => {},
};

it('shows the owner from server.cfg even when not in the directory', async () => {
  render(<OwnerAdminEditor {...base} serverCfgContent={'set qlx_owner "76561199580544522"\n'} />);
  await waitFor(() => expect(screen.getByDisplayValue('76561199580544522')).toBeInTheDocument());
});

it('lists every admin the server has, with no Adopt button or badges', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: '76561198087654321', level: 4 }], error: null });
  render(<OwnerAdminEditor {...base} />);
  expect(await screen.findByTestId('admin-row-76561198087654321')).toHaveTextContent('lvl 4');
  expect(screen.queryByRole('button', { name: /adopt/i })).not.toBeInTheDocument();
  expect(screen.queryByText(/set in-game|managed|not applied/i)).not.toBeInTheDocument();
});

it('shows the error and blocks editing when the server cannot be read', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: null, error: 'The server is unreachable, so admin levels could not be read.' });
  render(<OwnerAdminEditor {...base} />);
  expect(await screen.findByText(/unreachable/i)).toBeInTheDocument();
  expect(screen.getByText(/can't be edited/i)).toBeInTheDocument();
  expect(screen.queryByTestId(/^admin-row-/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
});

it('does not read live state without an instance id', async () => {
  render(<OwnerAdminEditor {...base} instanceId={null} />);
  await waitFor(() => expect(getOperators).toHaveBeenCalled());
  expect(getInstanceAdmins).not.toHaveBeenCalled();
});

it('reads the admin list on mount, before the tab is ever shown', async () => {
  // The modal keeps the editor mounted behind a hidden tab so the list is
  // preloaded: the tab opens filled and Save Preset includes it.
  render(<OwnerAdminEditor {...base} />);
  await waitFor(() => expect(getInstanceAdmins).toHaveBeenCalledWith(1));
});

it('reports nothing upward on mount', async () => {
  const onAdminEntriesChange = vi.fn();
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: '76561198012345678', level: 3 }], error: null });
  render(<OwnerAdminEditor {...base} onAdminEntriesChange={onAdminEntriesChange} />);
  await waitFor(() => expect(screen.getByText('Vex')).toBeInTheDocument());
  expect(onAdminEntriesChange).not.toHaveBeenCalled();
});

it('settles inside a stateful parent that feeds adminEntries back in', async () => {
  // The regression guard for the render loop: a parent that stores what the
  // child reports and passes it straight back. Mocking the child away, as the
  // modal suite does, is exactly how this class of bug ships.
  function Parent() {
    const [entries, setEntries] = React.useState(null);
    return <OwnerAdminEditor {...base} adminEntries={entries} onAdminEntriesChange={setEntries} />;
  }
  render(<Parent />);
  await waitFor(() => expect(getOperators).toHaveBeenCalled());
  const addInput = screen.getByPlaceholderText(/add operator as admin/i);
  await userEvent.click(addInput.parentElement.querySelector('button'));
  await userEvent.click(await screen.findByText('Vex'));
  await userEvent.click(screen.getByRole('button', { name: 'Add' }));
  expect(await screen.findByTestId('admin-row-76561198012345678')).toHaveTextContent('Vex');
});

it('adding an operator reports the new entry list upward', async () => {
  const onAdminEntriesChange = vi.fn();
  render(<OwnerAdminEditor {...base} onAdminEntriesChange={onAdminEntriesChange} />);
  await waitFor(() => expect(getOperators).toHaveBeenCalled());
  const addInput = screen.getByPlaceholderText(/add operator as admin/i);
  await userEvent.click(addInput.parentElement.querySelector('button'));
  await userEvent.click(await screen.findByText('Vex'));
  await userEvent.click(screen.getByRole('button', { name: 'Add' }));
  expect(onAdminEntriesChange).toHaveBeenCalledWith([{ steam_id64: '76561198012345678', level: 5 }]);
});

it('does not offer level 0 when adding', async () => {
  // A level-0 entry is "not an admin" -- removal is how a level is revoked.
  render(<OwnerAdminEditor {...base} />);
  await waitFor(() => expect(getOperators).toHaveBeenCalled());
  const levels = screen.getAllByRole('option').map((o) => o.value);
  expect(levels).toEqual(['1', '2', '3', '4', '5']);
});

it('Add to operators opens a prefilled modal in place and names the row on save', async () => {
  getInstanceAdmins.mockResolvedValue({ admins: [{ steam_id64: '76561198087654321', level: 4 }], error: null });
  const parentSubmit = vi.fn((e) => e.preventDefault());
  render(<form onSubmit={parentSubmit}><OwnerAdminEditor {...base} /></form>);
  await userEvent.click(await screen.findByRole('button', { name: /add to operators/i }));

  const dialog = await screen.findByRole('dialog');
  expect(within(dialog).getByLabelText('SteamID64')).toHaveValue('76561198087654321');
  expect(within(dialog).getByLabelText('Default admin level')).toHaveValue('4');

  getOperators.mockResolvedValue([{ id: 2, name: 'Rex', steam_id64: '76561198087654321', default_level: 4 }]);
  await userEvent.type(within(dialog).getByLabelText('Name'), 'Rex');
  await userEvent.click(within(dialog).getByRole('button', { name: /add operator/i }));

  expect(createOperator).toHaveBeenCalledWith({ name: 'Rex', steam_id64: '76561198087654321', default_level: 4 });
  expect(await screen.findByText('Rex')).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(parentSubmit).not.toHaveBeenCalled();
});
