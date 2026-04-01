"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type LeadStatus = "Lead In" | "Underwriting" | "Negotiation" | "Contract" | "Dispo";

type Lead = {
  id: string;
  address: string;
  beds: number;
  baths: number;
  sqft: number;
  asking: number;
  arv: number;
  rehab: number;
  status: LeadStatus;
  followUpDate: string;
  notes: string;
  createdAt: string;
};

const STATUS_ORDER: LeadStatus[] = [
  "Lead In",
  "Underwriting",
  "Negotiation",
  "Contract",
  "Dispo",
];

const STORAGE_KEY = "wholesale_ops_leads_v1";

const emptyForm: Omit<Lead, "id" | "createdAt"> = {
  address: "",
  beds: 3,
  baths: 2,
  sqft: 1200,
  asking: 0,
  arv: 0,
  rehab: 0,
  status: "Lead In",
  followUpDate: "",
  notes: "",
};

function formatUSD(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value || 0);
}

function calculateMAO(arv: number, rehab: number) {
  return arv * 0.7 - rehab;
}

export default function Home() {
  const [form, setForm] = useState(emptyForm);
  const [leads, setLeads] = useState<Lead[]>([]);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as Lead[];
      setLeads(parsed);
    } catch {
      setLeads([]);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(leads));
  }, [leads]);

  const kpis = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return {
      totalLeads: leads.length,
      offersSent: leads.filter((l) => l.status === "Negotiation" || l.status === "Contract" || l.status === "Dispo").length,
      contracts: leads.filter((l) => l.status === "Contract" || l.status === "Dispo").length,
      followUpsDue: leads.filter((l) => l.followUpDate && l.followUpDate <= today).length,
    };
  }, [leads]);

  const pipeline = useMemo(
    () =>
      STATUS_ORDER.map((stage) => ({
        stage,
        count: leads.filter((l) => l.status === stage).length,
      })),
    [leads],
  );

  const mao = useMemo(() => calculateMAO(form.arv, form.rehab), [form.arv, form.rehab]);

  function updateForm<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function submitLead(e: FormEvent) {
    e.preventDefault();

    if (!form.address.trim()) return;

    const next: Lead = {
      ...form,
      id: crypto.randomUUID(),
      createdAt: new Date().toISOString(),
    };

    setLeads((prev) => [next, ...prev]);
    setForm(emptyForm);
  }

  function moveStatus(id: string, status: LeadStatus) {
    setLeads((prev) => prev.map((lead) => (lead.id === id ? { ...lead, status } : lead)));
  }

  return (
    <main className="min-h-screen bg-zinc-100 p-4 text-zinc-900 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="rounded-2xl bg-white p-6 shadow-sm">
          <p className="text-sm text-zinc-500">SAHJONY Wholesale Command Center</p>
          <h1 className="mt-1 text-3xl font-bold">Wholesale Ops App — Phase 2</h1>
          <p className="mt-2 text-zinc-600">Lead intake, deal analyzer, and follow-up tracker are now live.</p>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card label="Total Leads" value={String(kpis.totalLeads)} />
          <Card label="Offers Sent" value={String(kpis.offersSent)} />
          <Card label="Contracts" value={String(kpis.contracts)} />
          <Card label="Follow-ups Due" value={String(kpis.followUpsDue)} />
        </section>

        <section className="grid gap-6 lg:grid-cols-3">
          <form onSubmit={submitLead} className="rounded-2xl bg-white p-6 shadow-sm lg:col-span-2">
            <h2 className="text-xl font-semibold">Lead Intake + Deal Analyzer</h2>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <Input label="Property Address" value={form.address} onChange={(v) => updateForm("address", v)} required />
              <Input label="Follow-up Date" type="date" value={form.followUpDate} onChange={(v) => updateForm("followUpDate", v)} />
              <Input label="Beds" type="number" value={String(form.beds)} onChange={(v) => updateForm("beds", Number(v))} />
              <Input label="Baths" type="number" value={String(form.baths)} onChange={(v) => updateForm("baths", Number(v))} />
              <Input label="Sq Ft" type="number" value={String(form.sqft)} onChange={(v) => updateForm("sqft", Number(v))} />
              <Input label="Asking Price" type="number" value={String(form.asking)} onChange={(v) => updateForm("asking", Number(v))} />
              <Input label="ARV" type="number" value={String(form.arv)} onChange={(v) => updateForm("arv", Number(v))} />
              <Input label="Rehab Estimate" type="number" value={String(form.rehab)} onChange={(v) => updateForm("rehab", Number(v))} />
            </div>

            <div className="mt-3">
              <label className="text-sm text-zinc-600">Notes</label>
              <textarea
                className="mt-1 min-h-20 w-full rounded-xl border border-zinc-300 p-3"
                value={form.notes}
                onChange={(e) => updateForm("notes", e.target.value)}
                placeholder="Motivation, condition, timeline, objections..."
              />
            </div>

            <div className="mt-4 rounded-xl bg-zinc-100 p-4">
              <p className="text-sm text-zinc-500">Analyzer Snapshot</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <p>Asking: <span className="font-semibold">{formatUSD(form.asking)}</span></p>
                <p>ARV: <span className="font-semibold">{formatUSD(form.arv)}</span></p>
                <p>MAO (70% rule): <span className="font-semibold">{formatUSD(mao)}</span></p>
              </div>
            </div>

            <button className="mt-4 rounded-xl bg-zinc-900 px-4 py-2 font-medium text-white" type="submit">
              Save Lead
            </button>
          </form>

          <div className="rounded-2xl bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Pipeline</h2>
            <ul className="mt-4 space-y-3">
              {pipeline.map((step) => (
                <li key={step.stage} className="flex items-center justify-between rounded-xl border border-zinc-200 p-3">
                  <span>{step.stage}</span>
                  <span className="rounded-full bg-zinc-900 px-3 py-1 text-sm text-white">{step.count}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="rounded-2xl bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold">Lead Tracker</h2>
            <p className="text-sm text-zinc-500">Stored locally in browser for now</p>
          </div>

          {leads.length === 0 ? (
            <p className="mt-4 text-zinc-500">No leads yet. Add your first lead above.</p>
          ) : (
            <div className="mt-4 overflow-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead>
                  <tr className="border-b border-zinc-200 text-zinc-500">
                    <th className="py-2">Address</th>
                    <th className="py-2">Asking</th>
                    <th className="py-2">ARV</th>
                    <th className="py-2">MAO</th>
                    <th className="py-2">Follow-up</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => {
                    const leadMao = calculateMAO(lead.arv, lead.rehab);
                    return (
                      <tr key={lead.id} className="border-b border-zinc-100">
                        <td className="py-3 pr-4">
                          <p className="font-medium">{lead.address}</p>
                          <p className="text-xs text-zinc-500">{lead.beds}bd / {lead.baths}ba · {lead.sqft} sqft</p>
                        </td>
                        <td className="py-3">{formatUSD(lead.asking)}</td>
                        <td className="py-3">{formatUSD(lead.arv)}</td>
                        <td className="py-3 font-semibold">{formatUSD(leadMao)}</td>
                        <td className="py-3">{lead.followUpDate || "-"}</td>
                        <td className="py-3">
                          <select
                            className="rounded-lg border border-zinc-300 px-2 py-1"
                            value={lead.status}
                            onChange={(e) => moveStatus(lead.id, e.target.value as LeadStatus)}
                          >
                            {STATUS_ORDER.map((status) => (
                              <option key={status} value={status}>
                                {status}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl bg-white p-5 shadow-sm">
      <p className="text-sm text-zinc-500">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  type = "text",
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
}) {
  return (
    <label>
      <span className="text-sm text-zinc-600">{label}</span>
      <input
        className="mt-1 w-full rounded-xl border border-zinc-300 p-2"
        type={type}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
