'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { Download, ShieldCheck } from 'lucide-react';
import { ResearchWorkspace } from '@/components/research-workspace';
import { researchRequest } from '@/lib/research';
import { useAuth } from '@/components/auth-provider';

type PlanPrice = { id: number; interval: string; amount_minor: number; currency: string };
type Plan = { id: number; code: string; tier: string; name: string; description: string; features: Record<string, boolean>; monthly_quotas: Record<string, number>; prices: PlanPrice[] };
type CreditPack = { id: number; code: string; name: string; amount_minor: number; currency: string; credits: number };
type Overview = { account: { billing_email: string; display_name: string }; subscription: null | { status: string; plan: Plan; period_start: string; period_end: string | null; cancel_at_period_end: boolean }; credits: number; currency: string; quota_remaining: Record<string, number>; monthly_usage: { feature: string; units: number; input_tokens: number; output_tokens: number; credits: number }[]; payment_mode: string };
type History = { orders: { id: string; purpose: string; amount_minor: number; currency: string; status: string; created_at: string; paid_at: string | null }[]; receipts: { id: string; invoice_number: string; status: string; amount_minor: number; tax_minor: number; currency: string; description: string; issued_at: string }[] };
type Order = { id: string; provider: string; provider_order_id: string; amount_minor: number; currency: string; key_id?: string };
type AdminCustomer = { customer_reference: string; user_id: string; username: string; email: string; billing_email: string; subscription: null | { plan: string; status: string; period_end: string | null }; credits: number };

const tabs = [['Overview','/dashboard/billing'],['Plans','/dashboard/billing/plans'],['Usage','/dashboard/billing/usage'],['History','/dashboard/billing/history'],['Settings','/dashboard/billing/settings']] as const;
function money(minor: number, currency: string) { return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(minor / 100); }

export function BillingPanel({ section = 'overview', admin = false }: { section?: string; admin?: boolean }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [creditPacks, setCreditPacks] = useState<CreditPack[]>([]);
  const [history, setHistory] = useState<History | null>(null);
  const [adminSummary, setAdminSummary] = useState<Record<string, unknown> | null>(null);
  const [customerQuery, setCustomerQuery] = useState('');
  const [customers, setCustomers] = useState<AdminCustomer[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [billingEmail, setBillingEmail] = useState('');
  const [billingName, setBillingName] = useState('');
  const { user } = useAuth();
  const load = useCallback(async () => {
    try {
      if (admin) setAdminSummary(await researchRequest<Record<string, unknown>>('billing/admin/summary/'));
      else {
        const [o, p, h, packs] = await Promise.all([
          researchRequest<Overview>('billing/'), researchRequest<Plan[]>('billing/plans/'),
          researchRequest<History>('billing/history/'), researchRequest<CreditPack[]>('billing/credit-packs/'),
        ]);
        setOverview(o); setPlans(p); setHistory(h); setCreditPacks(packs); setBillingEmail(o.account.billing_email); setBillingName(o.account.display_name);
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load billing information.'); }
  }, [admin]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);

  async function startCheckout(price: PlanPrice | CreditPack, purpose: 'subscription' | 'credit_topup' = 'subscription') {
    setBusy(true); setError('');
    try {
      const order = await researchRequest<Order>('billing/orders/', { body: {
        purpose, ...(purpose === 'subscription' ? { plan_price_id: price.id } : { credit_pack_id: price.id }),
        idempotency_key: crypto.randomUUID(),
      } });
      if (order.provider === 'mock') { setError('Order recorded in mock mode. No payment was taken; configure Razorpay test mode to try checkout.'); await load(); return; }
      const script = document.createElement('script'); script.src = 'https://checkout.razorpay.com/v1/checkout.js'; script.async = true;
      await new Promise<void>((resolve, reject) => { script.onload = () => resolve(); script.onerror = () => reject(new Error('Could not load Razorpay test checkout.')); document.head.appendChild(script); });
      const RazorpayCtor = (window as unknown as { Razorpay?: new (options: Record<string, unknown>) => { open: () => void } }).Razorpay;
      if (!RazorpayCtor || !order.key_id) throw new Error('Test checkout is not configured.');
      new RazorpayCtor({ key: order.key_id, amount: order.amount_minor, currency: order.currency,
        name: 'Scholivyn', description: purpose === 'subscription' ? 'Subscription plan' : 'Prepaid credits', order_id: order.provider_order_id,
        handler: async (result: Record<string, string>) => {
          try { await researchRequest('billing/verify-checkout/', { body: { order_id: order.id,
              razorpay_payment_id: result.razorpay_payment_id, razorpay_order_id: result.razorpay_order_id,
              razorpay_signature: result.razorpay_signature } }); await load(); }
          catch (e) { setError(e instanceof Error ? e.message : 'Payment verification failed.'); }
        }, theme: { color: '#173f8a' } }).open();
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start checkout.'); }
    finally { setBusy(false); }
  }

  async function cancel() {
    setBusy(true); setError('');
    try { await researchRequest('billing/subscription/cancel/', { body: {} }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Cancellation could not be scheduled.'); }
    finally { setBusy(false); }
  }

  async function saveSettings(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await researchRequest('billing/', { method: 'PATCH', body: { billing_email: billingEmail, display_name: billingName } });
      setNotice('Billing contact details saved.');
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Billing settings could not be saved.'); }
    finally { setBusy(false); }
  }

  async function searchCustomers(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('');
    try {
      const result = await researchRequest<{ results: AdminCustomer[] }>(`billing/admin/customers/?q=${encodeURIComponent(customerQuery)}`);
      setCustomers(result.results);
    } catch (e) { setError(e instanceof Error ? e.message : 'Customer lookup failed.'); }
  }

  return <ResearchWorkspace title={admin ? 'Billing administration' : 'Billing'}>
    <div className="mx-auto max-w-6xl p-5 sm:p-8">
      {!admin && <nav aria-label="Billing navigation" className="mb-6 flex flex-wrap gap-2">{tabs.map(([label, href]) => <Link key={href} href={href} className={`rounded-lg border px-3 py-2 text-sm ${section === label.toLowerCase() ? 'border-blue-700 bg-blue-50 text-blue-800' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'}`}>{label}</Link>)}{user?.is_staff && <Link href="/dashboard/admin/billing" className="ml-auto rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600">Billing admin</Link>}</nav>}
      {error && <div role="alert" className="mb-5 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">{error}</div>}
      {notice && <div role="status" className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">{notice}</div>}
      {admin ? <>{!adminSummary ? <p className="text-slate-600">Loading authorized billing metrics…</p> : <><section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[['Verified revenue', money(Number(adminSummary.verified_revenue_minor ?? 0),String(adminSummary.currency ?? 'INR'))],['Verified captures',String(adminSummary.verified_captures ?? 0)],['Pending orders',String(adminSummary.pending_orders ?? 0)],['Failed orders',String(adminSummary.failed_orders ?? 0)],['Available plans',String(adminSummary.available_plans ?? 0)],['AI usage records',String(adminSummary.ai_usage_records ?? 0)]].map(([label,value])=><article key={label} className="rounded-xl border border-slate-200 bg-white p-5"><p className="text-sm text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold text-[#102a43]">{value}</p></article>)}</section><section className="mt-5 rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-semibold text-[#102a43]">Operational notices</h2><p className="mt-1 text-sm text-slate-600">Revenue counts verified captured transactions only.</p>{Array.isArray(adminSummary.warnings)&&<ul className="mt-3 space-y-2">{(adminSummary.warnings as string[]).map(w=><li key={w} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-950">{w}</li>)}</ul>}</section><section className="mt-5 rounded-xl border border-slate-200 bg-white p-5"><h2 className="text-lg font-semibold text-[#102a43]">Customer lookup</h2><form onSubmit={(event)=>void searchCustomers(event)} className="mt-3 flex flex-col gap-2 sm:flex-row"><input value={customerQuery} onChange={(event)=>setCustomerQuery(event.target.value)} minLength={2} maxLength={120} placeholder="Email or username" className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"/><button className="rounded-lg bg-blue-800 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-900">Search</button></form><div className="mt-4 space-y-2">{customers.map(c=><article key={c.customer_reference} className="grid gap-2 rounded-lg border border-slate-200 p-4 sm:grid-cols-4"><div><p className="font-medium text-[#102a43]">{c.username}</p><p className="text-sm text-slate-600">{c.email}</p></div><p className="text-sm text-slate-600">Plan: {c.subscription?.plan ?? 'Free'} · {c.subscription?.status ?? 'free'}</p><p className="text-sm text-slate-600">Credits: {c.credits}</p><p className="break-all text-xs text-slate-500">{c.customer_reference}</p></article>)}</div></section></>}</>
      : !overview ? <p className="text-slate-600">Loading billing account…</p> : <>
        {section === 'overview' && <div className="grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border border-slate-200 bg-white p-6"><p className="text-sm text-slate-500">Current plan</p><h2 className="mt-1 text-2xl font-semibold capitalize text-[#102a43]">{overview.subscription?.plan.name ?? 'Free'}</h2><p className="mt-2 text-sm text-slate-600">Status: {overview.subscription?.status ?? 'free'}{overview.subscription?.period_end ? ` · renews/ends ${new Date(overview.subscription.period_end).toLocaleDateString()}` : ''}</p>{overview.subscription?.cancel_at_period_end && <p className="mt-2 text-sm text-amber-800">Cancellation is scheduled for the end of this period.</p>}<Link href="/dashboard/billing/plans" className="mt-5 inline-flex rounded-lg bg-blue-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-900">View plans</Link>{overview.subscription?.status === 'active' && !overview.subscription.cancel_at_period_end && <button disabled={busy} onClick={() => void cancel()} className="ml-3 rounded-lg border border-slate-300 px-4 py-2.5 text-sm hover:bg-slate-50 disabled:opacity-50">Cancel at period end</button>}</section><section className="rounded-2xl border border-slate-200 bg-white p-6"><p className="text-sm text-slate-500">Prepaid credits</p><p className="mt-1 text-3xl font-semibold text-[#102a43]">{overview.credits}</p><p className="mt-2 text-sm text-slate-600">Credit balance is separate from AI provider quotas.</p><p className="mt-4 flex items-center gap-2 text-xs text-slate-500"><ShieldCheck size={15}/> Mock payments are enabled unless test checkout is explicitly configured.</p></section>{Object.keys(overview.quota_remaining).length>0&&<section className="rounded-2xl border border-slate-200 bg-white p-6 lg:col-span-2"><h2 className="font-semibold text-[#102a43]">Remaining monthly quota</h2><div className="mt-3 flex flex-wrap gap-3">{Object.entries(overview.quota_remaining).map(([feature,remaining])=><span key={feature} className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{feature.replaceAll('_',' ')}: {remaining.toLocaleString()} remaining</span>)}</div></section>}</div>}
      {section === 'plans' && <section><h2 className="mb-4 text-xl font-semibold text-[#102a43]">Available plans</h2>{!plans.length ? <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">Plans are not currently configured by the administrator. No prices or quotas are being assumed.</div> : <div className="grid gap-4 md:grid-cols-3">{plans.map(plan=><article key={plan.id} className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="text-lg font-semibold text-[#102a43]">{plan.name}</h3><p className="mt-1 min-h-10 text-sm text-slate-600">{plan.description}</p><ul className="mt-4 space-y-2 text-sm text-slate-700">{Object.entries(plan.monthly_quotas).map(([feature, n])=><li key={feature}>{feature.replaceAll('_',' ')}: {n}/month</li>)}</ul>{plan.prices.map(price=><button key={price.id} disabled={busy} onClick={()=>void startCheckout(price)} className="mt-4 w-full rounded-lg bg-blue-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-900 disabled:opacity-50">{money(price.amount_minor,price.currency)} / {price.interval}</button>)}</article>)}</div>}{creditPacks.length>0&&<><h2 className="mb-4 mt-8 text-xl font-semibold text-[#102a43]">Prepaid credits</h2><div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{creditPacks.map(pack=><article key={pack.id} className="rounded-2xl border border-slate-200 bg-white p-5"><h3 className="font-semibold text-[#102a43]">{pack.name}</h3><p className="mt-2 text-sm text-slate-600">{pack.credits.toLocaleString()} credits</p><button disabled={busy} onClick={()=>void startCheckout(pack,'credit_topup')} className="mt-4 w-full rounded-lg border border-blue-700 px-4 py-2.5 text-sm font-semibold text-blue-800 hover:bg-blue-50 disabled:opacity-50">Buy for {money(pack.amount_minor,pack.currency)}</button></article>)}</div></>}</section>}
        {section === 'usage' && <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-4 text-xl font-semibold text-[#102a43]">Usage this month</h2>{!overview.monthly_usage.length ? <p className="text-sm text-slate-600">No billable usage events recorded this month.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b text-slate-500"><th className="p-3">Feature</th><th className="p-3">Units</th><th className="p-3">Input tokens</th><th className="p-3">Output tokens</th><th className="p-3">Credits</th></tr></thead><tbody>{overview.monthly_usage.map(x=><tr key={x.feature} className="border-b border-slate-100"><td className="p-3">{x.feature}</td><td className="p-3">{x.units}</td><td className="p-3">{x.input_tokens}</td><td className="p-3">{x.output_tokens}</td><td className="p-3">{x.credits}</td></tr>)}</tbody></table></div>}</section>}
        {section === 'history' && <section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="mb-4 text-xl font-semibold text-[#102a43]">Billing history</h2>{!history?.orders.length && !history?.receipts.length ? <p className="text-sm text-slate-600">No payment orders or receipts yet.</p> : <div className="space-y-3">{history?.orders.map(order=><article key={order.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-4"><div><p className="font-medium capitalize">{order.purpose.replaceAll('_',' ')} · {order.status}</p><p className="text-sm text-slate-500">{new Date(order.created_at).toLocaleString()}</p></div><strong>{money(order.amount_minor,order.currency)}</strong></article>)}{history?.receipts.map(receipt=><article key={receipt.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-4"><div><p className="font-medium">Receipt {receipt.invoice_number}</p><p className="text-sm text-slate-500">{receipt.description} · {new Date(receipt.issued_at).toLocaleDateString()}</p></div><a href={`/api/research/billing/invoices/${receipt.id}/download/`} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"><Download size={15}/>PDF</a></article>)}</div>}</section>}
        {section === 'settings' && <section className="max-w-2xl rounded-2xl border border-slate-200 bg-white p-6"><h2 className="text-xl font-semibold text-[#102a43]">Billing settings</h2><form onSubmit={(event)=>void saveSettings(event)} className="mt-5 space-y-4"><label className="block text-sm font-medium text-slate-700">Billing contact name<input value={billingName} onChange={(event)=>setBillingName(event.target.value)} maxLength={160} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><label className="block text-sm font-medium text-slate-700">Billing email<input type="email" value={billingEmail} onChange={(event)=>setBillingEmail(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2" /></label><button disabled={busy} className="rounded-lg bg-blue-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-900 disabled:opacity-50">Save billing details</button></form><p className="mt-5 text-sm text-slate-600">Recurring automatic renewals are disabled. No recurring payment mandate is created.</p><p className="mt-2 text-sm text-slate-600">Payment mode: {overview.payment_mode}</p></section>}
      </>}
    </div>
  </ResearchWorkspace>;
}
