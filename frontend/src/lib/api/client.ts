import axios, { type AxiosError } from 'axios';
import { env } from '../env';
import { tokenStore } from '../../auth/tokenStore';
import type { ApiErrorBody } from './types';

export const client = axios.create({
  baseURL: `${env.VITE_API_BASE_URL}/api/v1`,
  timeout: 60_000, // first inference after start-up can be slow
});

client.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// No refresh flow: any 401 (except a failed login) → clear the token and go to sign-in, keeping the page
client.interceptors.response.use(
  (res) => res,
  (error: AxiosError<ApiErrorBody>) => {
    const isLoginCall = error.config?.url?.includes('/auth/login');
    if (error.response?.status === 401 && !isLoginCall && !env.VITE_AUTH_DISABLED) {
      tokenStore.clear();
      if (window.location.pathname !== '/login') {
        const next = window.location.pathname + window.location.search;
        window.location.assign(`/login?next=${encodeURIComponent(next)}`);
      }
    }
    return Promise.reject(error);
  },
);
