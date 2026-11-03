-- Portefeuille virtuel partagé entre Streamlit et le moteur planifié.
-- À exécuter dans Supabase > SQL Editor. Aucun ordre réel n'est transmis.

create table if not exists public.virtual_portfolio (
    id text primary key check (id = 'main'),
    initial_capital numeric(18, 2) not null default 10000,
    cash numeric(18, 2) not null default 10000,
    positions jsonb not null default '[]'::jsonb check (jsonb_typeof(positions) = 'array'),
    closed_trades jsonb not null default '[]'::jsonb check (jsonb_typeof(closed_trades) = 'array'),
    last_cycle timestamptz,
    updated_at timestamptz not null default now(),
    version bigint not null default 0
);

create table if not exists public.virtual_cycle_runs (
    id text primary key,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null check (status in ('running', 'succeeded', 'failed', 'skipped')),
    opened_count integer not null default 0,
    closed_count integer not null default 0,
    message text
);

create index if not exists virtual_cycle_runs_started_at_idx
    on public.virtual_cycle_runs (started_at desc);

-- Accès client fermé : seule la clé service_role côté serveur/Actions peut écrire.
alter table public.virtual_portfolio enable row level security;
alter table public.virtual_cycle_runs enable row level security;

-- Création idempotente de l'état initial. Ne remplace jamais un portefeuille existant.
insert into public.virtual_portfolio (id, initial_capital, cash)
values ('main', 10000, 10000)
on conflict (id) do nothing;
