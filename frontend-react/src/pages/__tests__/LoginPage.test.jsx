import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import LoginPage from '../LoginPage';

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  loginContext: vi.fn(),
  login: vi.fn(),
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => mocks.navigate,
}));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ loginContext: mocks.loginContext }),
}));

vi.mock('../../services/auth', () => ({
  login: mocks.login,
}));

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.login.mockResolvedValue({
      data: {
        message: 'Login successful.',
        user: { username: 'admin', passwordChangeRequired: false },
      },
    });
  });

  it('renders a "Keep me signed in" checkbox, unchecked by default', () => {
    render(<LoginPage />);
    expect(screen.getByLabelText(/keep me signed in/i)).not.toBeChecked();
  });

  it('passes rememberMe=false to login() when the checkbox is left unchecked', async () => {
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'secret123' } });
    fireEvent.submit(screen.getByRole('button', { name: /login/i }));

    await waitFor(() => {
      expect(mocks.login).toHaveBeenCalledWith('admin', 'secret123', false);
    });
  });

  it('passes rememberMe=true to login() when the checkbox is checked', async () => {
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'secret123' } });
    fireEvent.click(screen.getByLabelText(/keep me signed in/i));
    fireEvent.submit(screen.getByRole('button', { name: /login/i }));

    await waitFor(() => {
      expect(mocks.login).toHaveBeenCalledWith('admin', 'secret123', true);
    });
  });
});
