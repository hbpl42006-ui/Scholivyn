'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { ApiError, authRequest, isProtectedRoute, type User } from '@/lib/auth';

type AuthContextValue = { user: User | null; loading: boolean; refreshUser: () => Promise<User | null>; logout: () => Promise<void> };
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const refreshUser = useCallback(async () => {
    try {
      const profile = await authRequest<User>('me');
      setUser(profile);
      return profile;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  useEffect(() => {
    let live = true;
    authRequest<User>('me').then((profile) => { if (live) setUser(profile); }).catch(async (cause: unknown) => {
      if (cause instanceof ApiError && cause.status === 401) {
        try {
          await authRequest('refresh', {});
          const profile = await authRequest<User>('me');
          if (live) setUser(profile);
          return;
        } catch { /* The session is no longer valid. */ }
      }
      if (live) setUser(null);
    }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (loading) return;
    if (isProtectedRoute(pathname) && !user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    if (user && (pathname === '/login' || pathname === '/register')) router.replace('/dashboard');
  }, [loading, pathname, router, user]);

  const logout = useCallback(async () => {
    try { await authRequest('logout', {}); } finally { setUser(null); router.replace('/login'); }
  }, [router]);
  const value = useMemo(() => ({ user, loading, refreshUser, logout }), [user, loading, refreshUser, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
