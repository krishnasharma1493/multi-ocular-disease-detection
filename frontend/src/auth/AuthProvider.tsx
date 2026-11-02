import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { client } from '../lib/api/client';
import { env } from '../lib/env';
import type { Envelope, LoginResult, User } from '../lib/api/types';
import { tokenStore } from './tokenStore';

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';
type AuthContextValue = {
  user: User | null;
  status: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthStatus>(() => (tokenStore.get() || env.VITE_AUTH_DISABLED ? 'loading' : 'anonymous'));

  useEffect(() => {
    if (status !== 'loading') return;
    client
      .get<Envelope<User>>('/users/me')
      .then((res) => {
        setUser(res.data.data);
        setStatus('authenticated');
      })
      .catch((err) => {
        // Keep the token when the server is merely unreachable; pages show the offline state
        if (err?.response) tokenStore.clear();
        setStatus(err?.response ? 'anonymous' : 'authenticated');
      });
  }, [status]);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await client.post<Envelope<LoginResult>>('/auth/login', { email, password });
    tokenStore.set(data.data.access_token);
    setUser(data.data.user);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    qc.clear();
    setUser(null);
    setStatus('anonymous');
  }, [qc]);

  const value = useMemo(() => ({ user, status, login, logout }), [user, status, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}
