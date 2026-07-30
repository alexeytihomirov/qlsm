import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('../api', () => ({
  default: {
    get: mocks.get,
  },
}));

import { downloadDraftFile } from '../draftApi';

describe('downloadDraftFile', () => {
  beforeEach(() => {
    mocks.get.mockReset();
  });

  it('requests a blob and returns the exact response object', async () => {
    const blob = new Blob([new Uint8Array([0, 255, 128, 65])]);
    mocks.get.mockResolvedValue({ data: blob });

    await expect(downloadDraftFile('draft-1', 'fonts/score.ttf')).resolves.toBe(blob);
    expect(mocks.get).toHaveBeenCalledWith(
      '/drafts/draft-1/file?path=fonts%2Fscore.ttf',
      { responseType: 'blob' },
    );
  });
});
