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

type BrainMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

const STATUS_ORDER: LeadStatus[] = ["Lead In", "Underwriting", "Negotiation", "Contract", "Dispo"];
const STORAGE_KEY = "wholesale_ops_leads_v2";

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

const starterMessages: BrainMessage[] = [
  {
    id: "intro",
    role: "assistant",
    text: "I’m your App Brain. Ask me: ‘next best action’, ‘which lead to follow up today’, or ‘analyze my newest lead’.",
  },
];

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

function nowDate() {
  return new Date().toISOString().slice(0, 10);
}

function topFollowUp(leads: Lead[]) {
  const today = nowDate();
  return leads
    .filter((l) => l.followUpDate && l.followUpDate <= today)
    .sort((a, b) => a.followUpDate.localeCompare(b.followUpDate));
}

function brainReply(input: string, leads: Lead[]) {
  const text = input.toLowerCase().trim();
  const newest = leads[0];
  const due = topFollowUp(leads);

  if (!leads.length) {
    return "You have no leads yet. Add one in Lead Intake, then I’ll start guiding next actions and offer strategy.";
  }

  if (text.includes("next") || text.includes("action")) {
    const hot = due[0] || newest;
    const mao = calculateMAO(hot.arv, hot.rehab);
    return `Priority: follow up ${hot.address}. Ask: motivation, timeline, and bottom number. Current ask is ${formatUSD(
      hot.asking,
    )}, model MAO is ${formatUSD(mao)}.`;
  }

  if (text.includes("follow") || text.includes("due")) {
    if (!due.length) return "No follow-ups due today. Next move: push underwriting leads into negotiation with a first offer.";
    const list = due.slice(0, 3).map((l) => `${l.address} (${l.followUpDate})`);
    return `Follow-ups due now: ${list.join(" • ")}`;
  }

  if (text.includes("analyze") || text.includes("mao") || text.includes("offer")) {
    const mao = calculateMAO(newest.arv, newest.rehab);
    const spread = newest.arv - newest.asking - newest.rehab;
    return `Newest lead: ${newest.address}. Ask ${formatUSD(newest.asking)}, ARV ${formatUSD(
      newest.arv,
    )}, rehab ${formatUSD(newest.rehab)}, MAO ${formatUSD(mao)}, estimated spread ${formatUSD(spread)}.`;
  }

  return "I can help with lead prioritization, MAO/offer strategy, and follow-up sequencing. Try: ‘next best action’ or ‘analyze my newest lead’.";
}

export default function Home() {
  const [form, setForm] = useState(emptyForm);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [brainInput, setBrainInput] = useState("");
  const [brainMessages, setBrainMessages] = useState<BrainMessage[]>(starterMessages);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      setLeads(JSON.parse(raw) as Lead[]);
    } catch {
      setLeads([]);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(leads));
  }, [leads]);

  const kpis = useMemo(() => {
    const today = nowDate();
    return {
      totalLeads: leads.length,
      offersSent: leads.filter((l) => ["Negotiation", "Contract", "Dispo"].includes(l.status)).length,
      contracts: leads.filter((l) => ["Contract", "Dispo"].includes(l.status)).length,
      followUpsDue: leads.filter((l) => l.followUpDate && l.followUpDate <= today).length,
    };
  }, [leads]);

  const pipeline = useMemo(
    () => STATUS_ORDER.map((stage) => ({ stage, count: leads.filter((l) => l.status === stage).length })),
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

  function sendBrainMessage(e: FormEvent) {
    e.preventDefault();
    if (!brainInput.trim()) return;

    const userMsg: BrainMessage = { id: crypto.randomUUID(), role: "user", text: brainInput.trim() };
    const assistantMsg: BrainMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      text: brainReply(brainInput, leads),
    };

    setBrainMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBrainInput("");
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,#1f2937_0%,#111827_35%,#020617_100%)] p-4 text-zinc-100 md:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="rounded-3xl border border-white/15 bg-white/5 p-6 backdrop-blur-md">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-300">SAHJONY CAPITAL</p>
          <h1 className="mt-2 text-3xl font-bold md:text-4xl">Premium Wholesale Operating System</h1>
          <p className="mt-2 text-zinc-300">App Brain enabled: lead intelligence, offer logic, and follow-up execution in one command center.</p>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard label="Total Leads" value={String(kpis.totalLeads)} />
          <KpiCard label="Offers Sent" value={String(kpis.offersSent)} />
          <KpiCard label="Contracts" value={String(kpis.contracts)} />
          <KpiCard label="Follow-ups Due" value={String(kpis.followUpsDue)} />
        </section>

        <section className="grid gap-6 xl:grid-cols-3">
          <form onSubmit={submitLead} className="rounded-3xl border border-white/15 bg-white/5 p-6 backdrop-blur-md xl:col-span-2">
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
              <label className="text-sm text-zinc-300">Notes</label>
              <textarea
                className="mt-1 min-h-20 w-full rounded-xl border border-white/20 bg-black/20 p-3 text-zinc-100 placeholder:text-zinc-500"
                value={form.notes}
                onChange={(e) => updateForm("notes", e.target.value)}
                placeholder="Motivation, condition, timeline, objections..."
              />
            </div>

            <div className="mt-4 rounded-2xl border border-emerald-400/30 bg-emerald-500/10 p-4">
              <p className="text-sm text-emerald-200">Analyzer Snapshot</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <p>Asking: <span className="font-semibold">{formatUSD(form.asking)}</span></p>
                <p>ARV: <span className="font-semibold">{formatUSD(form.arv)}</span></p>
                <p>MAO: <span className="font-semibold">{formatUSD(mao)}</span></p>
              </div>
            </div>

            <button className="mt-4 rounded-xl bg-white px-4 py-2 font-semibold text-zinc-900" type="submit">
              Save Lead
            </button>
          </form>

          <div className="rounded-3xl border border-white/15 bg-white/5 p-6 backdrop-blur-md">
            <h2 className="text-xl font-semibold">App Brain Console</h2>
            <p className="mt-1 text-sm text-zinc-300">Talk to your built-in assistant directly inside the app.</p>

            <div className="mt-4 h-64 space-y-2 overflow-y-auto rounded-2xl border border-white/15 bg-black/20 p-3">
              {brainMessages.map((msg) => (
                <div
                  key={msg.id}
                  className={`max-w-[90%] rounded-xl px-3 py-2 text-sm ${
                    msg.role === "assistant" ? "bg-indigo-500/20 border border-indigo-300/20" : "ml-auto bg-zinc-700/50"
                  }`}
                >
                  {msg.text}
                </div>
              ))}
            </div>

            <form onSubmit={sendBrainMessage} className="mt-3 flex gap-2">
              <input
                value={brainInput}
                onChange={(e) => setBrainInput(e.target.value)}
                placeholder="Ask the App Brain..."
                className="w-full rounded-xl border border-white/20 bg-black/30 px-3 py-2 text-sm"
              />
              <button type="submit" className="rounded-xl bg-indigo-500 px-3 py-2 text-sm font-semibold">
                Send
              </button>
            </form>
          </div>
        </section>

        <section className="rounded-3xl border border-white/15 bg-white/5 p-6 backdrop-blur-md">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xl font-semibold">Deal Pipeline + Follow-up Tracker</h2>
            <p className="text-xs text-zinc-300">Data currently stored locally in browser</p>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {pipeline.map((step) => (
              <div key={step.stage} className="rounded-xl border border-white/15 bg-black/20 p-3 text-center">
                <p className="text-xs text-zinc-300">{step.stage}</p>
                <p className="mt-1 text-2xl font-semibold">{step.count}</p>
              </div>
            ))}
          </div>

          {leads.length === 0 ? (
            <p className="mt-6 text-zinc-400">No leads yet. Add your first lead above.</p>
          ) : (
            <div className="mt-6 overflow-auto">
              <table className="w-full min-w-[920px] text-left text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-zinc-300">
                    <th className="py-2">Address</th>
                    <th className="py-2">Asking</th>
                    <th className="py-2">ARV</th>
                    <th className="py-2">MAO</th>
                    <th className="py-2">Follow-up</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => (
                    <tr key={lead.id} className="border-b border-white/5">
                      <td className="py-3 pr-4">
                        <p className="font-medium">{lead.address}</p>
                        <p className="text-xs text-zinc-400">
                          {lead.beds}bd / {lead.baths}ba · {lead.sqft} sqft
                        </p>
                      </td>
                      <td className="py-3">{formatUSD(lead.asking)}</td>
                      <td className="py-3">{formatUSD(lead.arv)}</td>
                      <td className="py-3 font-semibold">{formatUSD(calculateMAO(lead.arv, lead.rehab))}</td>
                      <td className="py-3">{lead.followUpDate || "-"}</td>
                      <td className="py-3">
                        <select
                          className="rounded-lg border border-white/20 bg-black/30 px-2 py-1"
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
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/15 bg-white/5 p-5 backdrop-blur-md">
      <p className="text-xs uppercase tracking-wider text-zinc-300">{label}</p>
      <p className="mt-2 text-3xl font-bold">{value}</p>
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
      <span className="text-sm text-zinc-300">{label}</span>
      <input
        className="mt-1 w-full rounded-xl border border-white/20 bg-black/20 p-2 text-zinc-100"
        type={type}
        value={value}
        required={required}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
