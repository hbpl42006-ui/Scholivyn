'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { Plus, FolderKanban, ArrowUpRight } from 'lucide-react';
import { ResearchWorkspace } from '@/components/research-workspace';
import { researchRequest, type Project } from '@/lib/research';

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => { researchRequest<Project[]>('projects/').then(setProjects).catch((e: Error) => setError(e.message)).finally(() => setLoading(false)); }, []);
  return <ResearchWorkspace title="Research projects">
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4"><p className="text-sm text-slate-600">Organize your active research and manuscripts.</p><Link href="/dashboard/projects/new" className="inline-flex items-center gap-2 rounded-lg bg-[#102a43] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#173b5c] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600"><Plus size={17} />New project</Link></div>
    {error && <p role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</p>}
    {loading ? <p className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">Loading your projects…</p> : projects.length ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{projects.map((project) => <Link key={project.id} href={`/dashboard/projects/${project.id}`} className="group rounded-2xl border border-slate-200 bg-white p-5 transition hover:border-blue-300 hover:shadow-sm"><div className="flex items-start justify-between"><span className="grid h-10 w-10 place-items-center rounded-xl bg-blue-50 text-blue-700"><FolderKanban size={20} /></span><ArrowUpRight className="text-slate-400 group-hover:text-blue-700" size={18} /></div><h2 className="mt-5 font-semibold text-[#102a43]">{project.title}</h2><p className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-slate-600">{project.description || project.research_field || 'Research project'}</p><div className="mt-5 flex justify-between text-xs text-slate-500"><span>{project.document_count} {project.document_count === 1 ? 'document' : 'documents'}</span><span className="capitalize">{project.status.replace('_', ' ')}</span></div></Link>)}</div> : <section className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center"><FolderKanban className="mx-auto text-blue-700" size={28} /><h2 className="mt-4 font-semibold text-[#102a43]">No research projects yet</h2><p className="mt-2 text-sm text-slate-600">Create a project to keep your research and manuscripts together.</p><Link href="/dashboard/projects/new" className="mt-5 inline-flex rounded-lg bg-[#102a43] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#173b5c]">Create project</Link></section>}
  </ResearchWorkspace>;
}
