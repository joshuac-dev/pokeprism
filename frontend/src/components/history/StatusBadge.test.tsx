import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import StatusBadge from './StatusBadge';

describe('StatusBadge status labels', () => {
  it.each([
    ['pending',   'Pending'],
    ['queued',    'Queued'],
    ['running',   'Running'],
    ['complete',  'Complete'],
    ['failed',    'Failed'],
    ['cancelled', 'Cancelled'],
  ] as const)('renders %s as "%s"', (status, label) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeTruthy();
  });

  it('falls back to raw status for unknown values', () => {
    render(<StatusBadge status="unknown_state" />);
    expect(screen.getByText('unknown_state')).toBeTruthy();
  });
});
