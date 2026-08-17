import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import InstanceOptionsRow from '../InstanceOptionsRow';

vi.mock('../../common/InfoTooltip', () => ({
  default: ({ text }) => <span data-testid="lan-rate-tooltip">{text}</span>,
}));

describe('InstanceOptionsRow', () => {
  it('renders the Ubuntu lan rate reason in the shared tooltip slot', () => {
    render(
      <InstanceOptionsRow
        lanRateEnabled={false}
        onLanRateChange={vi.fn()}
        lanRateDisabled={true}
        lanRateUnavailableReason="99k LAN rate is not compatible with Ubuntu."
      />
    );

    expect(screen.getByText('99k LAN Rate')).toBeInTheDocument();
    expect(screen.getByTestId('lan-rate-tooltip')).toHaveTextContent('99k LAN rate is not compatible with Ubuntu.');
  });
});
