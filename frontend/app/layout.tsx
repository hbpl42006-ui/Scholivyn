import './globals.css';
import { AuthProvider } from '@/components/auth-provider';

export const metadata = {
  title: 'Scholivyn — Research Smarter. Publish Better.',
  description: 'A precise workspace for stronger research manuscripts.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><AuthProvider>{children}</AuthProvider></body></html>;
}
