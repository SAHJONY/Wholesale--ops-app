"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { isSupabaseConfigured, supabase } from "@/lib/supabase";

const openclawWebhook = process.env.NEXT_PUBLIC_OPENCLAW_WEBHOOK_URL;

type LeadStatus = "Lead In" | "Underwriting" | "Negotiation" | "Contract" | "Dispo";

type Lead = {
  id: string;
  address: string;
  phone: string;
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

type BrainMessage = { id: string; role: "user" | "assistant"; text: string };
type ConsoleLine = { id: string; kind: "input" | "output"; text: string };
type AutoTask = { id: string; text: string; priority: "high" | "medium" | "low" };
type AuditEvent = { id: string; at: string; actor: string; action: string };
type Playbook = { id: string; name: string; prompt: string };

type SupabaseLeadRow = {
  id: string;
  address: string | null;
  phone: string | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  asking: number | null;
  arv: number | null;
  rehab: number | null;
  status: LeadStatus | null;
  follow_up_date: string | null;
  notes: string | null;
  created_at: string | null;
};

const STATUS_ORDER: LeadStatus[] = ["Lead In", "Underwriting", "Negotiation", "Contract", "Dispo"];
const STORAGE_KEY = "wholesale_ops_leads_v4";
const CONSOLE_STORAGE_KEY = "wholesale_ops_console_v1";
const HERO_IMAGE =
  "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=3840&q=80";

const PLAYBOOKS: Playbook[] = [
  { id: "acq-cold", name: "Cold Lead Conversion", prompt: "Build a 7-touch conversion plan for cold wholesale lead." },
  { id: "offer-tight", name: "Tight Margin Offer", prompt: "Create risk-safe offer ladder for a tight margin deal." },
  { id: "dispo-fast", name: "Fast Dispo", prompt: "Generate rapid buyer disposition plan for a signed contract." },
];

const DAILY_TARGETS = {
  leadsAdded: 25,
  offersSent: 8,
  followUpsDue: 15,
  contracts: 1,
};

const DATA_SOURCES = [
  { name: "PropStream", url: "https://www.propstream.com" },
  { name: "Propwire", url: "https://www.propwire.com" },
  { name: "BatchLeads", url: "https://batchleads.io" },
  { name: "Tavily Search", url: "https://tavily.com" },
  { name: "Zillow", url: "https://www.zillow.com" },
  { name: "Realtor.com", url: "https://www.realtor.com" },
  { name: "Redfin", url: "https://www.redfin.com" },
  { name: "Homes.com", url: "https://www.homes.com" },
  { name: "FSBO.com", url: "https://www.fsbo.com" },
  { name: "ForSaleByOwner.com", url: "https://www.forsalebyowner.com" },
  { name: "Craigslist Real Estate", url: "https://www.craigslist.org" },
  { name: "MLS / IDX Feeds", url: "https://www.nar.realtor" },
  { name: "County Records", url: "https://www.naco.org" },
  { name: "Skip Trace Vendors", url: "https://www.cyberbackgroundchecks.com/" },
];

const emptyForm: Omit<Lead, "id" | "createdAt"> = {
  address: "",
  phone: "",
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
  { id: "intro", role: "assistant", text: "App Brain online. Ask: next best action, follow-ups due, analyze newest lead." },
];

function formatUSD(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value || 0);
}

function calculateMAO(arv: number, rehab: number) {
  return arv * 0.7 - rehab;
}

function leadScore(lead: Lead) {
  let score = 50;
  const mao = calculateMAO(lead.arv, lead.rehab);
  if (lead.asking > 0 && mao > 0) {
    const spread = mao - lead.asking;
    if (spread > 25000) score += 25;
    else if (spread > 10000) score += 12;
    else score -= 8;
  }
  if (lead.followUpDate && lead.followUpDate <= nowDate()) score += 10;
  if (lead.status === "Negotiation") score += 8;
  if (lead.status === "Contract") score += 20;
  return Math.max(0, Math.min(100, score));
}

function nowDate() {
  return new Date().toISOString().slice(0, 10);
}

function brainReply(input: string, leads: Lead[]) {
  const text = input.toLowerCase().trim();
  const newest = leads[0];
  const due = leads.filter((l) => l.followUpDate && l.followUpDate <= nowDate()).sort((a, b) => a.followUpDate.localeCompare(b.followUpDate));

  if (!leads.length) return "No leads yet. Add one in Lead Intake and I’ll guide next actions.";
  if (text.includes("next") || text.includes("action")) {
    const hot = due[0] || newest;
    return `Priority: ${hot.address}. Anchor near ${formatUSD(calculateMAO(hot.arv, hot.rehab))} and confirm seller motivation today.`;
  }
  if (text.includes("follow") || text.includes("due")) {
    if (!due.length) return "No follow-ups due. Push underwriting leads into negotiation with first offer.";
    return `Due now: ${due.slice(0, 3).map((d) => `${d.address} (${d.followUpDate})`).join(" • ")}`;
  }
  if (text.includes("mao") || text.includes("analy") || text.includes("offer")) {
    return `${newest.address}: Ask ${formatUSD(newest.asking)} | ARV ${formatUSD(newest.arv)} | Rehab ${formatUSD(newest.rehab)} | MAO ${formatUSD(
      calculateMAO(newest.arv, newest.rehab),
    )}.`;
  }
  return "I can prioritize leads, calculate offer ranges, and follow-up sequencing.";
}

export default function Home() {
  const [form, setForm] = useState(emptyForm);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [brainInput, setBrainInput] = useState("");
  const [brainMessages, setBrainMessages] = useState<BrainMessage[]>(starterMessages);
  const [consoleInput, setConsoleInput] = useState("");
  const [consoleLines, setConsoleLines] = useState<ConsoleLine[]>([
    { id: "boot", kind: "output", text: "OpenClaw Console API ready. Try: status, pipeline summary, wake New lead inbound, skill:paperclip company status" },
  ]);
  const [search, setSearch] = useState("");
  const [dataMode, setDataMode] = useState<"supabase" | "local">("local");
  const [role, setRole] = useState<"CEO" | "ACQ" | "DISPO" | "OPS">("CEO");
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [report, setReport] = useState("");

  async function loadLeads() {
    if (isSupabaseConfigured && supabase) {
      const { data, error } = await supabase
        .from("leads")
        .select("*")
        .order("created_at", { ascending: false });

      if (!error && data) {
        const mapped: Lead[] = (data as SupabaseLeadRow[]).map((row) => ({
          id: row.id,
          address: row.address ?? "",
          phone: row.phone ?? "",
          beds: Number(row.beds ?? 0),
          baths: Number(row.baths ?? 0),
          sqft: Number(row.sqft ?? 0),
          asking: Number(row.asking ?? 0),
          arv: Number(row.arv ?? 0),
          rehab: Number(row.rehab ?? 0),
          status: (row.status as LeadStatus) ?? "Lead In",
          followUpDate: row.follow_up_date ?? "",
          notes: row.notes ?? "",
          createdAt: row.created_at ?? new Date().toISOString(),
        }));
        setLeads(mapped);
        setDataMode("supabase");
        return;
      }
    }

    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        setLeads(JSON.parse(raw) as Lead[]);
      } catch {
        setLeads([]);
      }
    }
    setDataMode("local");
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadLeads();
  }, []);

  useEffect(() => {
    const raw = localStorage.getItem(CONSOLE_STORAGE_KEY);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as ConsoleLine[];
      if (parsed.length) setConsoleLines(parsed);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (dataMode === "local") {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(leads));
    }
  }, [dataMode, leads]);

  useEffect(() => {
    localStorage.setItem(CONSOLE_STORAGE_KEY, JSON.stringify(consoleLines.slice(-80)));
  }, [consoleLines]);

  const filteredLeads = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return leads;
    return leads.filter((l) => l.address.toLowerCase().includes(q) || l.notes.toLowerCase().includes(q));
  }, [leads, search]);

  const kpis = useMemo(() => {
    const today = nowDate();
    const projectedProfit = leads.reduce((sum, l) => {
      const spread = calculateMAO(l.arv, l.rehab) - l.asking;
      return spread > 0 ? sum + spread : sum;
    }, 0);
    return {
      totalLeads: leads.length,
      offersSent: leads.filter((l) => ["Negotiation", "Contract", "Dispo"].includes(l.status)).length,
      contracts: leads.filter((l) => ["Contract", "Dispo"].includes(l.status)).length,
      followUpsDue: leads.filter((l) => l.followUpDate && l.followUpDate <= today).length,
      projectedProfit,
    };
  }, [leads]);

  const pipeline = useMemo(
    () => STATUS_ORDER.map((stage) => ({ stage, count: leads.filter((l) => l.status === stage).length })),
    [leads],
  );

  const liveTasks = useMemo<AutoTask[]>(() => {
    const today = nowDate();
    const generated: AutoTask[] = [];

    leads
      .filter((l) => l.followUpDate && l.followUpDate <= today)
      .slice(0, 5)
      .forEach((lead) => {
        generated.push({
          id: `due-${lead.id}`,
          text: `Follow up ${lead.address} now — follow-up date is due (${lead.followUpDate}).`,
          priority: "high",
        });
      });

    leads
      .filter((l) => l.status === "Negotiation" && !l.phone)
      .slice(0, 3)
      .forEach((lead) => {
        generated.push({
          id: `phone-${lead.id}`,
          text: `Add phone number for ${lead.address} to enable Bland AI outreach.`,
          priority: "medium",
        });
      });

    leads
      .filter((l) => calculateMAO(l.arv, l.rehab) > 0 && l.asking > 0 && l.asking <= calculateMAO(l.arv, l.rehab))
      .slice(0, 3)
      .forEach((lead) => {
        generated.push({
          id: `offer-${lead.id}`,
          text: `Send offer for ${lead.address} — asking is within modeled MAO range.`,
          priority: "high",
        });
      });

    if (!generated.length) {
      generated.push({
        id: "seed",
        text: "No urgent automation tasks. Add new leads or set follow-up dates to trigger automations.",
        priority: "low",
      });
    }

    return generated;
  }, [leads]);

  const mao = useMemo(() => calculateMAO(form.arv, form.rehab), [form.arv, form.rehab]);

  const sla = useMemo(() => {
    const today = nowDate();
    const overdue = leads.filter((l) => l.followUpDate && l.followUpDate < today).length;
    const dueToday = leads.filter((l) => l.followUpDate && l.followUpDate === today).length;
    return { overdue, dueToday };
  }, [leads]);

  function logAudit(action: string) {
    setAudit((prev) => [
      { id: crypto.randomUUID(), at: new Date().toISOString(), actor: role, action },
      ...prev,
    ].slice(0, 50));
  }

  function updateForm<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function submitLead(e: FormEvent) {
    e.preventDefault();
    if (!form.address.trim()) return;

    const next: Lead = { ...form, id: crypto.randomUUID(), createdAt: new Date().toISOString() };

    if (dataMode === "supabase" && supabase) {
      await supabase.from("leads").insert({
        id: next.id,
        address: next.address,
        phone: next.phone,
        beds: next.beds,
        baths: next.baths,
        sqft: next.sqft,
        asking: next.asking,
        arv: next.arv,
        rehab: next.rehab,
        status: next.status,
        follow_up_date: next.followUpDate || null,
        notes: next.notes,
      });
      await loadLeads();
    } else {
      setLeads((prev) => [next, ...prev]);
    }

    logAudit(`Created lead: ${next.address}`);

    setForm(emptyForm);
  }

  async function moveStatus(id: string, status: LeadStatus) {
    if (dataMode === "supabase" && supabase) {
      await supabase.from("leads").update({ status }).eq("id", id);
      await loadLeads();
      logAudit(`Updated status to ${status}`);
      return;
    }
    setLeads((prev) => prev.map((lead) => (lead.id === id ? { ...lead, status } : lead)));
    logAudit(`Updated status to ${status}`);
  }

  async function deleteLead(id: string) {
    if (dataMode === "supabase" && supabase) {
      await supabase.from("leads").delete().eq("id", id);
      await loadLeads();
      logAudit(`Deleted lead ${id}`);
      return;
    }
    setLeads((prev) => prev.filter((lead) => lead.id !== id));
    logAudit(`Deleted lead ${id}`);
  }

  function exportCsv() {
    const headers = ["address", "phone", "beds", "baths", "sqft", "asking", "arv", "rehab", "mao", "status", "followUpDate", "notes"];
    const rows = leads.map((l) => [
      l.address,
      l.phone,
      l.beds,
      l.baths,
      l.sqft,
      l.asking,
      l.arv,
      l.rehab,
      Math.round(calculateMAO(l.arv, l.rehab)),
      l.status,
      l.followUpDate,
      l.notes.replaceAll(",", " "),
    ]);
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "wholesale-leads.csv";
    link.click();
  }

  async function sendBrainMessage(e: FormEvent) {
    e.preventDefault();
    if (!brainInput.trim()) return;

    const prompt = brainInput.trim();
    const userMsg: BrainMessage = { id: crypto.randomUUID(), role: "user", text: prompt };
    setBrainMessages((prev) => [...prev, userMsg]);
    setBrainInput("");

    if (!openclawWebhook) {
      setBrainMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: "OpenClaw webhook is not configured yet. Add NEXT_PUBLIC_OPENCLAW_WEBHOOK_URL to activate live OpenClaw brain mode.",
        },
      ]);
      return;
    }

    try {
      const res = await fetch(openclawWebhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: prompt, leads }),
      });

      const data = await res.json().catch(() => ({}));
      const text = data?.reply || data?.message || "OpenClaw responded with no message.";
      setBrainMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "assistant", text }]);
      return;
    } catch {
      setBrainMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: "OpenClaw request failed. Verify webhook URL, gateway reachability, and auth.",
        },
      ]);
      return;
    }
  }

  async function runConsoleCommand(e: FormEvent) {
    e.preventDefault();
    if (!consoleInput.trim()) return;

    const cmd = consoleInput.trim();
    setConsoleLines((prev) => [...prev, { id: crypto.randomUUID(), kind: "input", text: `$ ${cmd}` }]);
    setConsoleInput("");

    try {
      const res = await fetch("/api/openclaw/console", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: cmd,
          leads,
          history: consoleLines.slice(-10).map((l) => l.text),
        }),
      });
      const data = await res.json().catch(() => ({}));
      const line = data?.message || data?.error || "No response";
      setConsoleLines((prev) => [...prev, { id: crypto.randomUUID(), kind: "output", text: line }]);
      if (data?.assistantReply) {
        setConsoleLines((prev) => [...prev, { id: crypto.randomUUID(), kind: "output", text: `AI: ${data.assistantReply}` }]);
      }
      logAudit(`Console command: ${cmd}`);
    } catch {
      setConsoleLines((prev) => [...prev, { id: crypto.randomUUID(), kind: "output", text: "Console request failed." }]);
    }
  }

  function generateCeoReport() {
    const top = leads.slice(0, 3).map((l) => l.address).join(", ") || "No leads";
    const text = `CEO REPORT\nLeads: ${kpis.totalLeads}\nOffers Sent: ${kpis.offersSent}\nContracts: ${kpis.contracts}\nProjected Profit: ${formatUSD(
      kpis.projectedProfit,
    )}\nSLA Overdue: ${sla.overdue}\nFocus List: ${top}`;
    setReport(text);
    logAudit("Generated CEO report");
  }

  function copyLeadLink(leadId: string) {
    const url = `${window.location.origin}${window.location.pathname}#lead-${leadId}`;
    navigator.clipboard.writeText(url);
    logAudit(`Copied lead deep link ${leadId}`);
  }

  async function emailCeoReport() {
    if (!report) {
      generateCeoReport();
      return;
    }
    await fetch("/api/reports/ceo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report }),
    });
    logAudit("Emailed CEO report");
  }

  return (
    <main className="min-h-screen bg-[#020617] text-zinc-100">
      <div
        className="absolute inset-0 opacity-25"
        style={{
          backgroundImage: `linear-gradient(to bottom, rgba(2,6,23,0.3), rgba(2,6,23,0.95)), url('${HERO_IMAGE}')`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          backgroundAttachment: "fixed",
        }}
      />

      <div className="relative mx-auto max-w-7xl space-y-6 p-4 md:p-6">
        <section className="sticky top-2 z-20 rounded-2xl border border-white/15 bg-black/40 p-3 backdrop-blur-xl">
          <div className="flex flex-wrap gap-2 text-xs">
            {[
              ["#overview", "Overview"],
              ["#enterprise", "Enterprise"],
              ["#intake", "Intake"],
              ["#tracker", "Tracker"],
              ["#automation", "Automation"],
              ["#data-hub", "Data Hub"],
              ["#console", "Console"],
            ].map(([href, label]) => (
              <a key={href} href={href} className="rounded-lg border border-white/20 px-2 py-1 hover:bg-white/10">
                {label}
              </a>
            ))}
          </div>
        </section>

        <section id="overview" className="rounded-3xl border border-white/15 bg-white/5 p-6 backdrop-blur-xl">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-300">SAHJONY CAPITAL • PHASE 3</p>
          <h1 className="mt-2 text-3xl font-bold md:text-5xl">Premium Wholesale Operating System</h1>
          <p className="mt-2 text-zinc-300">Data Mode: <span className="font-semibold uppercase">{dataMode}</span> {dataMode === "local" && "(Supabase env not active)"}</p>
          <p className="mt-1 text-zinc-300">OpenClaw Brain: <span className="font-semibold uppercase">{openclawWebhook ? "connected" : "local intelligence"}</span></p>
          <p className="mt-1 text-zinc-300">Paperclip Skill: <span className="font-semibold uppercase">enabled via console command prefix</span></p>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <KpiCard label="Total Leads" value={String(kpis.totalLeads)} />
          <KpiCard label="Offers Sent" value={String(kpis.offersSent)} />
          <KpiCard label="Contracts" value={String(kpis.contracts)} />
          <KpiCard label="Follow-ups Due" value={String(kpis.followUpsDue)} />
          <KpiCard label="Projected Profit" value={formatUSD(kpis.projectedProfit)} />
        </section>

        <section className="rounded-3xl border border-lime-200/20 bg-white/5 p-6 backdrop-blur-xl">
          <h2 className="text-xl font-semibold">Daily Operating Plan (Profit Mode)</h2>
          <p className="mt-1 text-sm text-zinc-300">Hard quotas + fail-safe triggers to force execution every day.</p>

          <div className="mt-3 grid gap-3 md:grid-cols-4">
            {[
              ["Leads Added", kpis.totalLeads, DAILY_TARGETS.leadsAdded],
              ["Offers Sent", kpis.offersSent, DAILY_TARGETS.offersSent],
              ["Follow-ups Due", kpis.followUpsDue, DAILY_TARGETS.followUpsDue],
              ["Contracts", kpis.contracts, DAILY_TARGETS.contracts],
            ].map(([label, current, target]) => {
              const ratio = Number(target) === 0 ? 1 : Number(current) / Number(target);
              const ok = ratio >= 1;
              return (
                <div key={String(label)} className="rounded-xl border border-white/15 bg-black/20 p-3">
                  <p className="text-xs text-zinc-300">{label}</p>
                  <p className="mt-1 text-lg font-semibold">
                    {String(current)} / {String(target)}
                  </p>
                  <p className={`text-xs ${ok ? "text-emerald-300" : "text-amber-300"}`}>
                    {ok ? "On target" : "Behind target"}
                  </p>
                </div>
              );
            })}
          </div>

          <div className="mt-3 rounded-xl border border-white/15 bg-black/20 p-3 text-sm text-zinc-200">
            <p>Fail-safe triggers:</p>
            <ul className="mt-1 list-inside list-disc text-zinc-300">
              <li>If offers sent &lt; 8 by 2pm: run console macro <code>offer strategy</code> and send 3 offers immediately.</li>
              <li>If follow-ups due &gt; 10: run Bland AI calls on top 5 due leads before end of day.</li>
              <li>If no contract by Friday: double inbound lead volume next week and tighten MAO discipline.</li>
            </ul>
          </div>
        </section>

        <section id="enterprise" className="rounded-3xl border border-fuchsia-200/20 bg-white/5 p-6 backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xl font-semibold">Enterprise Control Layer</h2>
            <div className="flex items-center gap-2">
              <span className="text-sm text-zinc-300">Role</span>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as "CEO" | "ACQ" | "DISPO" | "OPS")}
                className="rounded-lg border border-white/20 bg-black/30 px-2 py-1"
              >
                <option>CEO</option>
                <option>ACQ</option>
                <option>DISPO</option>
                <option>OPS</option>
              </select>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            <span className="rounded-lg border border-red-300/30 bg-red-500/10 px-2 py-1 text-red-200">SLA Overdue: {sla.overdue}</span>
            <span className="rounded-lg border border-amber-300/30 bg-amber-500/10 px-2 py-1 text-amber-200">Due Today: {sla.dueToday}</span>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={generateCeoReport} className="rounded-xl bg-fuchsia-400 px-3 py-2 text-sm font-semibold text-black">
              Generate CEO Report
            </button>
            <button type="button" onClick={emailCeoReport} className="rounded-xl border border-fuchsia-300/40 px-3 py-2 text-sm font-semibold text-fuchsia-100">
              Email CEO Report
            </button>
          </div>

          {report ? (
            <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-white/15 bg-black/30 p-3 text-xs text-zinc-200">{report}</pre>
          ) : null}

          <div className="mt-3 rounded-xl border border-white/15 bg-black/20 p-3">
            <p className="text-sm font-semibold">Audit Log</p>
            <div className="mt-2 max-h-40 space-y-1 overflow-y-auto text-xs text-zinc-300">
              {audit.length === 0 ? <p>No events yet.</p> : audit.map((a) => <p key={a.id}>{a.at} • {a.actor} • {a.action}</p>)}
            </div>
          </div>
        </section>

        <section id="playbooks" className="rounded-3xl border border-emerald-200/20 bg-white/5 p-6 backdrop-blur-xl">
          <h2 className="text-xl font-semibold">Enterprise Playbooks</h2>
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            {PLAYBOOKS.map((pb) => (
              <button
                type="button"
                key={pb.id}
                onClick={() => setConsoleInput(`skill:paperclip ${pb.prompt}`)}
                className="rounded-xl border border-white/15 bg-black/20 p-3 text-left text-sm"
              >
                <p className="font-semibold">{pb.name}</p>
                <p className="mt-1 text-xs text-zinc-300">Load into console</p>
              </button>
            ))}
          </div>
        </section>

        <section id="data-hub" className="rounded-3xl border border-sky-200/20 bg-white/5 p-6 backdrop-blur-xl">
          <h2 className="text-xl font-semibold">Data Intelligence Hub (Fortune Mode)</h2>
          <p className="mt-1 text-sm text-zinc-300">
            Connector architecture ready for PropStream, Propwire, BatchLeads and additional data providers.
          </p>

          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {DATA_SOURCES.map((source) => (
              <div key={source.name} className="rounded-xl border border-white/15 bg-black/20 p-3">
                <div className="flex items-center justify-between gap-2">
                  <a className="font-semibold underline-offset-2 hover:underline" href={source.url} target="_blank" rel="noreferrer">{source.name}</a>
                  <span className="rounded-md border border-sky-300/30 px-2 py-1 text-xs text-sky-200">Connector Ready</span>
                </div>
                <button
                  type="button"
                  onClick={() => setConsoleInput(`Create secure ingestion pipeline for ${source.name} with authenticated access`)}
                  className="mt-2 rounded-lg border border-sky-300/30 px-2 py-1 text-xs text-sky-200"
                >
                  Build Integration
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-3">
          <form id="intake" onSubmit={submitLead} className="rounded-3xl border border-amber-200/20 bg-gradient-to-br from-white/10 to-white/5 p-6 backdrop-blur-xl xl:col-span-2">
            <h2 className="text-xl font-semibold">Lead Intake + Analyzer</h2>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <Input label="Property Address" value={form.address} onChange={(v) => updateForm("address", v)} required />
              <Input label="Contact Phone" value={form.phone} onChange={(v) => updateForm("phone", v)} />
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
              <textarea className="mt-1 min-h-20 w-full rounded-xl border border-white/20 bg-black/30 p-3 text-zinc-100" value={form.notes} onChange={(e) => updateForm("notes", e.target.value)} />
            </div>

            <div className="mt-4 rounded-2xl border border-indigo-400/30 bg-indigo-500/10 p-4">
              <p className="text-sm text-indigo-200">Analyzer Snapshot</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-3">
                <p>Asking: <span className="font-semibold">{formatUSD(form.asking)}</span></p>
                <p>ARV: <span className="font-semibold">{formatUSD(form.arv)}</span></p>
                <p>MAO: <span className="font-semibold">{formatUSD(mao)}</span></p>
              </div>
            </div>

            <button className="mt-4 rounded-xl bg-white px-4 py-2 font-semibold text-zinc-900" type="submit">Save Lead</button>
          </form>

          <div className="rounded-3xl border border-indigo-200/20 bg-gradient-to-br from-indigo-500/10 to-white/5 p-6 backdrop-blur-xl">
            <h2 className="text-xl font-semibold">App Brain Console</h2>
            <div className="mt-4 h-64 space-y-2 overflow-y-auto rounded-2xl border border-white/15 bg-black/30 p-3">
              {brainMessages.map((msg) => (
                <div key={msg.id} className={`max-w-[90%] rounded-xl px-3 py-2 text-sm ${msg.role === "assistant" ? "border border-indigo-300/20 bg-indigo-500/20" : "ml-auto bg-zinc-700/50"}`}>
                  {msg.text}
                </div>
              ))}
            </div>
            <form onSubmit={sendBrainMessage} className="mt-3 flex gap-2">
              <input value={brainInput} onChange={(e) => setBrainInput(e.target.value)} placeholder="Ask the App Brain..." className="w-full rounded-xl border border-white/20 bg-black/40 px-3 py-2 text-sm" />
              <button type="submit" className="rounded-xl bg-indigo-500 px-3 py-2 text-sm font-semibold">Send</button>
            </form>
          </div>
        </section>

        <section id="tracker" className="rounded-3xl border border-white/15 bg-white/5 p-6 backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xl font-semibold">Lead Tracker</h2>
            <div className="flex gap-2">
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search leads" className="rounded-xl border border-white/20 bg-black/30 px-3 py-2 text-sm" />
              <button onClick={exportCsv} type="button" className="rounded-xl border border-white/20 px-3 py-2 text-sm">Export CSV</button>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {pipeline.map((step) => (
              <div key={step.stage} className="rounded-xl border border-white/15 bg-black/20 p-3 text-center">
                <p className="text-xs text-zinc-300">{step.stage}</p>
                <p className="mt-1 text-2xl font-semibold">{step.count}</p>
              </div>
            ))}
          </div>

          {filteredLeads.length === 0 ? (
            <p className="mt-6 text-zinc-400">No matching leads yet.</p>
          ) : (
            <div className="mt-6 overflow-auto">
              <table className="w-full min-w-[960px] text-left text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-zinc-300">
                    <th className="py-2">Address</th>
                    <th className="py-2">Phone</th>
                    <th className="py-2">Asking</th>
                    <th className="py-2">ARV</th>
                    <th className="py-2">MAO</th>
                    <th className="py-2">Score</th>
                    <th className="py-2">Follow-up</th>
                    <th className="py-2">Status</th>
                    <th className="py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeads.map((lead) => (
                    <tr id={`lead-${lead.id}`} key={lead.id} className="border-b border-white/5">
                      <td className="py-3 pr-4"><p className="font-medium"><a href={`#lead-${lead.id}`} className="hover:underline">{lead.address}</a></p><p className="text-xs text-zinc-400">{lead.beds}bd / {lead.baths}ba · {lead.sqft} sqft</p></td>
                      <td className="py-3">{lead.phone || "-"}</td>
                      <td className="py-3">{formatUSD(lead.asking)}</td>
                      <td className="py-3">{formatUSD(lead.arv)}</td>
                      <td className="py-3 font-semibold">{formatUSD(calculateMAO(lead.arv, lead.rehab))}</td>
                      <td className="py-3">
                        <span className="rounded-full border border-indigo-300/30 px-2 py-1 text-xs">{leadScore(lead)}</span>
                      </td>
                      <td className="py-3">{lead.followUpDate || "-"}</td>
                      <td className="py-3">
                        <select className="rounded-lg border border-white/20 bg-black/30 px-2 py-1" value={lead.status} onChange={(e) => moveStatus(lead.id, e.target.value as LeadStatus)}>
                          {STATUS_ORDER.map((status) => <option key={status} value={status}>{status}</option>)}
                        </select>
                      </td>
                      <td className="py-3">
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={async () => {
                              if (!lead.phone) return;
                              await fetch("/api/bland/call", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  phoneNumber: lead.phone,
                                  task: `Call ${lead.address} lead and ask motivation, timeline, and lowest acceptable price.`,
                                }),
                              });
                            }}
                            className="rounded-lg border border-emerald-300/30 px-2 py-1 text-emerald-200"
                          >
                            AI Call
                          </button>
                          <button
                            type="button"
                            onClick={() => copyLeadLink(lead.id)}
                            className="rounded-lg border border-sky-300/30 px-2 py-1 text-sky-200"
                          >
                            Copy Link
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (role !== "CEO") {
                                setConsoleLines((prev) => [...prev, { id: crypto.randomUUID(), kind: "output", text: "Delete restricted: switch role to CEO." }]);
                                return;
                              }
                              deleteLead(lead.id);
                            }}
                            className="rounded-lg border border-red-300/30 px-2 py-1 text-red-200"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section id="automation" className="rounded-3xl border border-cyan-200/20 bg-white/5 p-6 backdrop-blur-xl">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xl font-semibold">Automation Task Engine</h2>
            <span className="rounded-xl border border-cyan-300/40 px-3 py-1 text-xs text-cyan-200">Live Data Mode</span>
          </div>

          <div className="mt-3 space-y-2">
            {liveTasks.map((task) => (
              <div key={task.id} className="w-full rounded-xl border border-white/15 bg-black/20 p-3 text-left text-sm">
                <span className={`mr-2 rounded-md px-2 py-1 text-xs ${task.priority === "high" ? "bg-red-500/20 text-red-200" : task.priority === "medium" ? "bg-amber-500/20 text-amber-200" : "bg-zinc-500/20 text-zinc-200"}`}>
                  {task.priority}
                </span>
                {task.text}
              </div>
            ))}
          </div>
        </section>

        <section id="console" className="rounded-3xl border border-emerald-200/20 bg-black/40 p-6 backdrop-blur-xl">
          <h2 className="text-xl font-semibold">Phase 5 — OpenClaw Console API</h2>
          <p className="mt-1 text-sm text-zinc-300">Terminal-style command console routed through OpenClaw hooks.</p>

          <div className="mt-4 h-64 overflow-y-auto rounded-2xl border border-emerald-400/20 bg-black p-3 font-mono text-sm">
            {consoleLines.map((line) => (
              <div key={line.id} className={line.kind === "input" ? "text-emerald-300" : "text-zinc-200"}>
                {line.text}
              </div>
            ))}
          </div>

          <form onSubmit={runConsoleCommand} className="mt-3 flex gap-2">
            <input
              value={consoleInput}
              onChange={(e) => setConsoleInput(e.target.value)}
              placeholder="Enter OpenClaw command..."
              className="w-full rounded-xl border border-emerald-400/30 bg-black px-3 py-2 font-mono text-sm"
            />
            <button type="submit" className="rounded-xl bg-emerald-500 px-3 py-2 text-sm font-semibold text-black">
              Run
            </button>
          </form>

          <div className="mt-3 flex flex-wrap gap-2">
            {[
              "status",
              "pipeline summary",
              "next best action",
              "offer strategy",
              "wake New lead inbound",
              "paperclip company status",
              "skill:weather Houston forecast",
              "skill:github list open PRs",
              "skill:tavily-search find cash buyer lists in Houston",
            ].map((macro) => (
              <button
                key={macro}
                type="button"
                onClick={() => setConsoleInput(macro)}
                className="rounded-lg border border-emerald-400/30 px-2 py-1 text-xs text-emerald-200"
              >
                {macro}
              </button>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/20 bg-gradient-to-br from-white/10 to-white/5 p-5 backdrop-blur-xl">
      <p className="text-xs uppercase tracking-wider text-zinc-300">{label}</p>
      <p className="mt-2 text-3xl font-bold">{value}</p>
    </div>
  );
}

function Input({ label, value, onChange, type = "text", required = false }: { label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean }) {
  return (
    <label>
      <span className="text-sm text-zinc-300">{label}</span>
      <input className="mt-1 w-full rounded-xl border border-white/20 bg-black/30 p-2 text-zinc-100" type={type} value={value} required={required} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
