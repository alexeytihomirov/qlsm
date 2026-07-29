import { render, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import FileTreeRowMenu from '../FileTreeRowMenu';

const CAPS = { canCreateFolder: true, allowedExtensions: ['.cfg', '.txt'] };

describe('FileTreeRowMenu folder upload', () => {
  it('marks the folder upload input as multiple', () => {
    const { container } = render(
      <FileTreeRowMenu itemType="folder" capabilities={CAPS} onUploadToFolder={vi.fn()} />,
    );
    const input = container.querySelector('input[type="file"]');
    expect(input).not.toBeNull();
    expect(input.multiple).toBe(true);
  });

  it('passes all selected files to onUploadToFolder', () => {
    const onUploadToFolder = vi.fn();
    const { container } = render(
      <FileTreeRowMenu itemType="folder" capabilities={CAPS} onUploadToFolder={onUploadToFolder} />,
    );
    const input = container.querySelector('input[type="file"]');
    const files = [new File(['a'], 'a.cfg'), new File(['b'], 'b.cfg')];
    fireEvent.change(input, { target: { files } });
    expect(onUploadToFolder).toHaveBeenCalledTimes(1);
    const arg = onUploadToFolder.mock.calls[0][0];
    expect(Array.from(arg).map(f => f.name)).toEqual(['a.cfg', 'b.cfg']);
  });
});

describe('FileTreeRowMenu new folder', () => {
  it('shows a New Folder action for a folder below max depth', async () => {
    const user = userEvent.setup();
    const onNewFolderInFolder = vi.fn();
    const { getByLabelText, getByText } = render(
      <FileTreeRowMenu
        itemType="folder"
        capabilities={CAPS}
        isMaxDepth={false}
        onNewFolderInFolder={onNewFolderInFolder}
      />,
    );
    await user.click(getByLabelText('folder actions'));
    await user.click(getByText('New Folder'));
    expect(onNewFolderInFolder).toHaveBeenCalledTimes(1);
  });

  it('hides New Folder once the folder is at max depth', async () => {
    const user = userEvent.setup();
    const { getByLabelText, queryByText } = render(
      <FileTreeRowMenu
        itemType="folder"
        capabilities={CAPS}
        isMaxDepth
        onNewFolderInFolder={vi.fn()}
      />,
    );
    await user.click(getByLabelText('folder actions'));
    expect(queryByText('New Folder')).toBeNull();
  });
});
