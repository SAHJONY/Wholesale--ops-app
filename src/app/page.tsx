const kpis = [
  { label: "New Leads", value: "12" },
  { label: "Offers Sent", value: "5" },
  { label: "Contracts", value: "1" },
  { label: "Follow-ups Due", value: "9" },
];

const pipeline = [
  { stage: "Lead In", count: 18 },
  { stage: "Underwriting", count: 7 },
  { stage: "Negotiation", count: 3 },
  { stage: "Contract", count: 1 },
  { stage: "Dispo", count: 1 },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-zinc-100 p-6 text-zinc-900">
      <div className="mx-auto max-w-6xl space-y-6">
        <section className="rounded-2xl bg-white p-6 shadow-sm">
          <p className="text-sm text-zinc-500">SAHJONY Wholesale Command Center</p>
          <h1 className="mt-1 text-3xl font-bold">Wholesale Ops App</h1>
          <p className="mt-2 text-zinc-600">
            Intake leads, underwrite fast, send offers, and stay on top of follow-ups.
          </p>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {kpis.map((item) => (
            <div key={item.label} className="rounded-2xl bg-white p-5 shadow-sm">
              <p className="text-sm text-zinc-500">{item.label}</p>
              <p className="mt-2 text-3xl font-semibold">{item.value}</p>
            </div>
          ))}
        </section>

        <section className="grid gap-6 lg:grid-cols-3">
          <div className="rounded-2xl bg-white p-6 shadow-sm lg:col-span-2">
            <h2 className="text-xl font-semibold">Deal Pipeline</h2>
            <ul className="mt-4 space-y-3">
              {pipeline.map((step) => (
                <li
                  key={step.stage}
                  className="flex items-center justify-between rounded-xl border border-zinc-200 p-3"
                >
                  <span>{step.stage}</span>
                  <span className="rounded-full bg-zinc-900 px-3 py-1 text-sm text-white">
                    {step.count}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-2xl bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Next Actions</h2>
            <ul className="mt-4 space-y-2 text-zinc-700">
              <li>• Follow up Chandler St counteroffer</li>
              <li>• Send 3 new cash offers</li>
              <li>• Pull buyer list for dispo</li>
              <li>• Review follow-ups due today</li>
            </ul>
          </div>
        </section>
      </div>
    </main>
  );
}
