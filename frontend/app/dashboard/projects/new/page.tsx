'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';
import { ResearchWorkspace } from '@/components/research-workspace';
import { researchRequest, type Project } from '@/lib/research';

export default function NewProjectPage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setSaving(true);
    const form = new FormData(event.currentTarget);
    try {
      const project = await researchRequest<Project>('projects/', { body: {
        title: form.get('title'), description: form.get('description'), research_field: form.get('research_field'),
        keywords: String(form.get('keywords') ?? '').split(',').map((x) => x.trim()).filter(Boolean), status: 'active',
      }});
      router.push(`/dashboard/projects/${project.id}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to create project.'); setSaving(false); }
  }
  return <ResearchWorkspace title="Create a project"><form onSubmit={submit} className="max-w-2xl space-y-5 rounded-2xl border border-slate-200 bg-white p-5 sm:p-8">
    {error && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    <label className="block text-sm font-medium text-slate-800">Project title<input required maxLength={200} name="title" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5 font-normal focus:border-blue-600 focus:outline-none" placeholder="e.g. Coastal water quality study" /></label>
    <label className="block text-sm font-medium text-slate-800">Research field<input maxLength={120} name="research_field" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5 font-normal focus:border-blue-600 focus:outline-none" placeholder="Environmental science" /></label>
    <label className="block text-sm font-medium text-slate-800">Description<textarea name="description" rows={4} className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5 font-normal focus:border-blue-600 focus:outline-none" placeholder="What are you investigating?" /></label>
    <label className="block text-sm font-medium text-slate-800">Keywords <span className="font-normal text-slate-500">(comma separated)</span><input name="keywords" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2.5 font-normal focus:border-blue-600 focus:outline-none" /></label>
    <div className="flex gap-3"><button disabled={saving} className="rounded-lg bg-[#102a43] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#173b5c] disabled:cursor-not-allowed disabled:bg-slate-400">{saving ? 'Creating…' : 'Create project'}</button><Link href="/dashboard/projects" className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">Cancel</Link></div>
  </form></ResearchWorkspace>;
}
