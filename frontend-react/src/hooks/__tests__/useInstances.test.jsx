import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../../services/api';
import {
    getInstancePollingInterval,
    useInstances,
} from '../useInstances';

const mocks = vi.hoisted(() => ({
    setIsLoadingGlobal: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
    lanRateAction: null,
    isLanRateModalOpen: false,
    requestToggleLanRate: vi.fn(),
    confirmToggleLanRate: vi.fn(),
    closeLanRateModal: vi.fn(),
}));

vi.mock('../../services/api', () => ({
    getInstances: vi.fn(),
    deleteInstance: vi.fn(),
    restartInstance: vi.fn(),
    updateInstanceLanRate: vi.fn(),
}));

vi.mock('../../components/NotificationProvider', () => ({
    useNotification: () => ({
        showSuccess: mocks.showSuccess,
        showError: mocks.showError,
    }),
}));

vi.mock('../../contexts/LoadingContext', () => ({
    useLoading: () => ({ setIsLoadingGlobal: mocks.setIsLoadingGlobal }),
}));

vi.mock('../useInstanceLanRate', () => ({
    useInstanceLanRate: () => ({
        lanRateAction: mocks.lanRateAction,
        isLanRateModalOpen: mocks.isLanRateModalOpen,
        requestToggleLanRate: mocks.requestToggleLanRate,
        confirmToggleLanRate: mocks.confirmToggleLanRate,
        closeLanRateModal: mocks.closeLanRateModal,
    }),
}));

describe('getInstancePollingInterval', () => {
    it('uses the fast interval for transitional instances', () => {
        expect(getInstancePollingInterval([{ status: 'restarting' }])).toBe(3000);
    });

    it('uses the slow interval for settled updated instances', () => {
        expect(getInstancePollingInterval([{ status: 'updated' }])).toBe(30000);
    });

    it('prioritizes transitional instances over updated instances', () => {
        expect(getInstancePollingInterval([
            { status: 'updated' },
            { status: 'configuring' },
        ])).toBe(3000);
    });

    it('does not poll settled running instances', () => {
        expect(getInstancePollingInterval([{ status: 'running' }])).toBeNull();
    });
});

describe('useInstances polling', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        vi.clearAllMocks();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('refreshes updated instances only at the slow interval', async () => {
        api.getInstances.mockResolvedValue([{ status: 'updated' }]);
        renderHook(() => useInstances());

        await act(async () => {});
        expect(api.getInstances).toHaveBeenCalledTimes(1);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(29999);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(1);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(2);
    });

    it('refreshes transitional instances at the fast interval', async () => {
        api.getInstances.mockResolvedValue([{ status: 'restarting' }]);
        renderHook(() => useInstances());

        await act(async () => {});
        await act(async () => {
            await vi.advanceTimersByTimeAsync(2999);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(1);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(2);
    });

    it('replaces the fast interval when a refresh settles to updated', async () => {
        api.getInstances
            .mockResolvedValueOnce([{ status: 'configuring' }])
            .mockResolvedValueOnce([{ status: 'updated' }])
            .mockResolvedValue([{ status: 'updated' }]);
        renderHook(() => useInstances());

        await act(async () => {});
        await act(async () => {
            await vi.advanceTimersByTimeAsync(3000);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(2);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(3000);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(2);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(27000);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(3);
    });

    it('stops interval polling when a refresh settles to running', async () => {
        api.getInstances
            .mockResolvedValueOnce([{ status: 'restarting' }])
            .mockResolvedValueOnce([{ status: 'running' }]);
        renderHook(() => useInstances());

        await act(async () => {});
        await act(async () => {
            await vi.advanceTimersByTimeAsync(3000);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(2);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(30000);
        });
        expect(api.getInstances).toHaveBeenCalledTimes(2);
    });
});
