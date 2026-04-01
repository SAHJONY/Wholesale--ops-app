create extension if not exists "pgcrypto";

create table if not exists public.leads (
  id uuid primary key default gen_random_uuid(),
  address text not null,
  beds numeric,
  baths numeric,
  sqft numeric,
  asking numeric,
  arv numeric,
  rehab numeric,
  status text not null default 'Lead In',
  follow_up_date date,
  notes text,
  created_at timestamptz not null default now()
);

alter table public.leads enable row level security;

create policy "Allow read leads" on public.leads for select using (true);
create policy "Allow insert leads" on public.leads for insert with check (true);
create policy "Allow update leads" on public.leads for update using (true);
create policy "Allow delete leads" on public.leads for delete using (true);
