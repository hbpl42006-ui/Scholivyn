'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { Bell, BookOpen, FileText, LayoutDashboard, LogOut, Menu, Settings, UserRound, X } from 'lucide-react';
import { useAuth } from '@/components/auth-provider';

const items = [['Overview', '/dashboard', LayoutDashboard], ['Projects', '/dashboard/projects', BookOpen], ['Documents', '/dashboard/projects', FileText], ['Profile', '/dashboard/profile', UserRound], ['Settings', '/dashboard/settings', Settings]] as const;

export default function Dashboard() {
  const { user, loading, logout } = useAuth();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const initials = (user?.full_name || user?.username || 'R').split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('');
  return (
    <div className="min-h-screen bg-[#f8fafc] md:flex">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white p-5 md:block">
        <Link href="/" className="flex items-center gap-3 px-2 py-3 font-semibold text-[#102a43]"><span className="grid h-8 w-8 place-items-center rounded-lg bg-[#102a43] text-white"><BookOpen size={16} /></span>Scholivyn</Link>
        <p className="mb-4 mt-10 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">Workspace</p>
        <nav aria-label="Workspace navigation" className="space-y-1">{items.map(([name, href, Icon]) => <Link href={href} aria-current={pathname === href ? 'page' : undefined} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors hover:bg-slate-50 ${pathname === href ? 'bg-blue-50 font-medium text-blue-700 hover:bg-blue-50' : 'text-slate-600'}`} key={name}><Icon size={17} />{name}</Link>)}</nav>
        <button onClick={logout} className="mt-10 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-600 transition-colors hover:bg-slate-50"><LogOut size={17} />Sign out</button>
      </aside>
      <main className="min-w-0 flex-1">
        <header className="relative flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-5 py-4 sm:px-6 sm:py-5 md:px-10">
          <div className="flex items-center gap-3"><button aria-label="Toggle workspace navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)} className="grid h-10 w-10 place-items-center rounded-lg border border-slate-200 text-slate-600 md:hidden">{menuOpen ? <X size={18} /> : <Menu size={18} />}</button><div><p className="text-xs text-slate-500 sm:text-sm">Your research workspace</p><h1 className="mt-1 text-lg font-semibold text-[#102a43] sm:text-2xl">{pathname === '/dashboard' ? `Welcome${user?.full_name ? `, ${user.full_name.split(' ')[0]}` : ''}` : pathname.endsWith('/profile') ? 'Profile' : 'Account settings'}</h1></div></div>
          <div className="relative flex items-center gap-2"><span className="hidden text-sm text-slate-600 sm:block">{loading ? 'Loading profile…' : user?.email}</span><button aria-label="Profile menu" aria-expanded={profileOpen} onClick={() => setProfileOpen(!profileOpen)} className="grid h-10 w-10 place-items-center rounded-full bg-blue-100 text-sm font-semibold text-blue-800">{initials}</button>{profileOpen && <div className="absolute right-0 top-12 z-20 w-52 rounded-xl border border-slate-200 bg-white p-2 shadow-lg"><p className="truncate px-3 py-2 text-xs text-slate-500">{user?.email}</p><Link onClick={() => setProfileOpen(false)} href="/dashboard/profile" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"><UserRound size={16} />Profile</Link><Link onClick={() => setProfileOpen(false)} href="/dashboard/settings" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"><Settings size={16} />Settings</Link><button onClick={logout} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"><LogOut size={16} />Sign out</button></div>}<button aria-label="Notifications" className="rounded-full border border-slate-200 p-2.5 text-slate-600 transition-colors hover:bg-slate-50"><Bell size={18} /></button></div>
          {menuOpen && <nav aria-label="Mobile workspace navigation" className="absolute inset-x-0 top-full z-10 border-b border-slate-200 bg-white p-3 shadow-md md:hidden">{items.map(([name, href, Icon]) => <Link onClick={() => setMenuOpen(false)} href={href} key={name} className="flex items-center gap-3 rounded-lg px-3 py-3 text-sm text-slate-700 hover:bg-slate-50"><Icon size={17} />{name}</Link>)}<button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm text-slate-700 hover:bg-slate-50"><LogOut size={17} />Sign out</button></nav>}
        </header>
        <div className="mx-auto max-w-6xl p-5 sm:p-6 md:p-10">
          {pathname !== '/dashboard' ? pathname.endsWith('/profile') ? <ProfileContent user={user} /> : <section className="rounded-2xl border border-slate-200 bg-white p-6 sm:p-8"><p className="text-sm font-semibold uppercase tracking-widest text-blue-700">Preferences</p><h2 className="mt-2 text-xl font-semibold text-[#102a43]">Account settings</h2><p className="mt-2 max-w-xl text-sm leading-6 text-slate-600">Manage your Scholivyn account details and sign-in preferences.</p><Link href="/dashboard/profile" className="mt-6 inline-flex rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-[#102a43] transition hover:bg-slate-50">View profile</Link></section> : <>
            <section className="rounded-2xl bg-[#102a43] p-6 text-white sm:p-7 md:p-9"><p className="text-sm text-blue-200">Research workspace</p><h2 className="mt-2 text-xl font-semibold sm:text-2xl">Your next research step starts here.</h2><p className="mt-2 max-w-lg text-sm leading-6 text-slate-300">Your projects and manuscripts will appear in this workspace as you add them.</p></section>
            <div className="mt-6 grid gap-4 sm:mt-8 sm:grid-cols-2"><Link href="/dashboard/projects" className="block"><EmptyState id="projects" icon={<BookOpen size={26} />} title="Manage research projects" text="Create and organize research projects, notes and manuscripts." /></Link><Link href="/dashboard/projects" className="block"><EmptyState id="documents" icon={<FileText size={26} />} title="Manage manuscripts" text="Upload manuscripts and follow their extraction status." /></Link></div>
          </>}
        </div>
      </main>
    </div>
  );
}

function EmptyState({ id, icon, title, text }: { id: string; icon: React.ReactNode; title: string; text: string }) { return <section id={id} className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-10 text-center sm:px-8"><span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-blue-700">{icon}</span><h2 className="mt-4 font-semibold text-[#102a43]">{title}</h2><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">{text}</p></section>; }
function ProfileContent({ user }: { user: ReturnType<typeof useAuth>['user'] }) { return <section className="rounded-2xl border border-slate-200 bg-white p-6 sm:p-8"><p className="text-sm font-semibold uppercase tracking-widest text-blue-700">Your account</p><h2 className="mt-2 text-xl font-semibold text-[#102a43]">Profile</h2><dl className="mt-7 grid gap-5 sm:grid-cols-2">{[['Name', user?.full_name || user?.username], ['Email', user?.email], ['Username', user?.username], ['Role', user?.role]].map(([label, value]) => <div key={label}><dt className="text-sm text-slate-500">{label}</dt><dd className="mt-1 font-medium capitalize text-slate-900">{value || '—'}</dd></div>)}</dl></section>; }
