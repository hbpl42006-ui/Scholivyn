import { describe, expect, it } from 'vitest';
import { isProtectedRoute } from './auth';

describe('protected workspace routes', () => {
  it('requires authentication for every dashboard route', () => {
    expect(isProtectedRoute('/dashboard')).toBe(true);
    expect(isProtectedRoute('/dashboard/projects')).toBe(true);
    expect(isProtectedRoute('/dashboard/projects/abc/documents/def')).toBe(true);
    expect(isProtectedRoute('/dashboard/citations')).toBe(true);
    expect(isProtectedRoute('/dashboard/citations/abc')).toBe(true);
    expect(isProtectedRoute('/dashboard/journals')).toBe(true);
    expect(isProtectedRoute('/dashboard/journals/abc')).toBe(true);
    expect(isProtectedRoute('/dashboard/publication-readiness')).toBe(true);
  });

  it('does not classify public authentication routes as protected', () => {
    expect(isProtectedRoute('/login')).toBe(false);
    expect(isProtectedRoute('/verify-email')).toBe(false);
  });
});
