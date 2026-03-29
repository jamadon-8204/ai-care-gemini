create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table public.families (
  id uuid primary key default gen_random_uuid(),
  external_key text not null unique,
  family_name text not null,
  timezone text not null default 'Asia/Seoul',
  notes text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.care_recipients (
  id uuid primary key default gen_random_uuid(),
  family_id uuid not null references public.families(id) on delete cascade,
  external_key text not null unique,
  full_name text not null,
  display_name text not null,
  birth_year integer,
  prompt_profile jsonb not null default '{}'::jsonb,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.family_contacts (
  id uuid primary key default gen_random_uuid(),
  family_id uuid not null references public.families(id) on delete cascade,
  name text not null,
  relationship text not null,
  phone_number text,
  is_primary boolean not null default false,
  notification_priority smallint not null default 1 check (notification_priority between 1 and 9),
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.device_installations (
  id uuid primary key default gen_random_uuid(),
  care_recipient_id uuid not null references public.care_recipients(id) on delete cascade,
  client_id text not null unique,
  device_label text,
  platform text not null default 'web_pwa',
  last_seen_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.conversation_sessions (
  id uuid primary key default gen_random_uuid(),
  care_recipient_id uuid not null references public.care_recipients(id) on delete cascade,
  device_installation_id uuid references public.device_installations(id) on delete set null,
  conversation_key text not null unique,
  external_client_id text,
  source text not null default 'web_pwa',
  transport text not null default 'gemini_live',
  status text not null default 'active' check (status in ('active', 'completed', 'interrupted', 'error')),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  ended_reason text,
  model_name text,
  voice_name text,
  last_resumption_handle text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (ended_at is null or ended_at >= started_at)
);

create table public.session_connections (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.conversation_sessions(id) on delete cascade,
  external_client_id text,
  gemini_resumption_handle text,
  resumed boolean not null default false,
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  close_code integer,
  close_reason text,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (closed_at is null or closed_at >= opened_at)
);

create table public.conversation_turns (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.conversation_sessions(id) on delete cascade,
  connection_id uuid references public.session_connections(id) on delete set null,
  care_recipient_id uuid not null references public.care_recipients(id) on delete cascade,
  turn_index integer not null check (turn_index > 0),
  turn_status text not null default 'complete' check (turn_status in ('complete', 'partial', 'discarded')),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  user_transcript text,
  assistant_transcript text,
  user_transcript_status text not null default 'captured' check (user_transcript_status in ('captured', 'unclear', 'empty')),
  assistant_transcript_status text not null default 'captured' check (assistant_transcript_status in ('captured', 'empty')),
  needs_repeat_prompt boolean not null default false,
  hearing_aid_prompted boolean not null default false,
  family_call_prompted boolean not null default false,
  raw_turn jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (session_id, turn_index),
  check (completed_at is null or completed_at >= started_at)
);

create table public.turn_health_signals (
  id uuid primary key default gen_random_uuid(),
  turn_id uuid not null unique references public.conversation_turns(id) on delete cascade,
  session_id uuid not null references public.conversation_sessions(id) on delete cascade,
  care_recipient_id uuid not null references public.care_recipients(id) on delete cascade,
  signal_date date not null,
  observed_at timestamptz not null,
  extraction_method text not null default 'llm' check (extraction_method in ('rule_based', 'llm', 'manual')),
  extraction_version text not null default 'v1',
  review_status text not null default 'auto' check (review_status in ('auto', 'confirmed', 'corrected', 'rejected')),
  pain_present boolean,
  pain_locations text[],
  pain_severity text check (pain_severity in ('mild', 'moderate', 'severe')),
  meal_status text check (meal_status in ('good', 'reduced', 'poor', 'skipped')),
  sleep_status text check (sleep_status in ('good', 'light', 'poor', 'insomnia', 'frequent_waking')),
  hearing_aid_status text check (hearing_aid_status in ('wearing', 'not_wearing', 'sometimes')),
  activity_status text check (activity_status in ('normal', 'limited', 'unable', 'resting')),
  farm_work_status text check (farm_work_status in ('possible', 'limited', 'unable')),
  dizziness_present boolean,
  fall_present boolean,
  needs_family_followup boolean not null default false,
  risk_level text not null default 'normal' check (risk_level in ('normal', 'watch', 'urgent')),
  family_followup_reason text,
  note_summary text,
  evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (pain_severity is null or pain_present = true),
  check (pain_locations is null or pain_present = true),
  check (needs_family_followup = false or family_followup_reason is not null)
);

create table public.daily_summaries (
  id uuid primary key default gen_random_uuid(),
  care_recipient_id uuid not null references public.care_recipients(id) on delete cascade,
  summary_date date not null,
  summary_status text not null default 'draft' check (summary_status in ('draft', 'final')),
  risk_level text not null default 'normal' check (risk_level in ('normal', 'watch', 'urgent')),
  needs_family_followup boolean not null default false,
  family_followup_reason text,
  summary_text text not null default '',
  highlights text[] not null default '{}'::text[],
  structured_snapshot jsonb not null default '{}'::jsonb,
  source_turn_count integer not null default 0,
  source_signal_count integer not null default 0,
  generated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (care_recipient_id, summary_date),
  check (needs_family_followup = false or family_followup_reason is not null)
);

create table public.alert_events (
  id uuid primary key default gen_random_uuid(),
  care_recipient_id uuid not null references public.care_recipients(id) on delete cascade,
  family_contact_id uuid references public.family_contacts(id) on delete set null,
  turn_signal_id uuid references public.turn_health_signals(id) on delete set null,
  daily_summary_id uuid references public.daily_summaries(id) on delete set null,
  alert_type text not null,
  severity text not null check (severity in ('watch', 'urgent')),
  status text not null default 'pending' check (status in ('pending', 'sent', 'acknowledged', 'dismissed', 'failed')),
  title text not null,
  message text not null,
  triggered_at timestamptz not null default now(),
  delivered_at timestamptz,
  acknowledged_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (turn_signal_id is not null or daily_summary_id is not null)
);

create index families_created_at_idx on public.families (created_at desc);
create index families_external_key_idx on public.families (external_key);
create index care_recipients_family_id_idx on public.care_recipients (family_id);
create index care_recipients_active_idx on public.care_recipients (active);
create index care_recipients_external_key_idx on public.care_recipients (external_key);
create index family_contacts_family_id_idx on public.family_contacts (family_id);
create index family_contacts_active_idx on public.family_contacts (active);
create index device_installations_recipient_id_idx on public.device_installations (care_recipient_id);
create index conversation_sessions_recipient_started_idx on public.conversation_sessions (care_recipient_id, started_at desc);
create index conversation_sessions_status_idx on public.conversation_sessions (status);
create index conversation_sessions_client_id_idx on public.conversation_sessions (external_client_id);
create index session_connections_session_opened_idx on public.session_connections (session_id, opened_at desc);
create index conversation_turns_recipient_completed_idx on public.conversation_turns (care_recipient_id, completed_at desc);
create index conversation_turns_session_idx on public.conversation_turns (session_id);
create index turn_health_signals_recipient_date_idx on public.turn_health_signals (care_recipient_id, signal_date desc);
create index turn_health_signals_followup_idx on public.turn_health_signals (needs_family_followup, risk_level);
create index daily_summaries_recipient_date_idx on public.daily_summaries (care_recipient_id, summary_date desc);
create index alert_events_recipient_status_idx on public.alert_events (care_recipient_id, status, triggered_at desc);

create trigger set_families_updated_at
before update on public.families
for each row execute function public.set_updated_at();

create trigger set_care_recipients_updated_at
before update on public.care_recipients
for each row execute function public.set_updated_at();

create trigger set_family_contacts_updated_at
before update on public.family_contacts
for each row execute function public.set_updated_at();

create trigger set_device_installations_updated_at
before update on public.device_installations
for each row execute function public.set_updated_at();

create trigger set_conversation_sessions_updated_at
before update on public.conversation_sessions
for each row execute function public.set_updated_at();

create trigger set_session_connections_updated_at
before update on public.session_connections
for each row execute function public.set_updated_at();

create trigger set_conversation_turns_updated_at
before update on public.conversation_turns
for each row execute function public.set_updated_at();

create trigger set_turn_health_signals_updated_at
before update on public.turn_health_signals
for each row execute function public.set_updated_at();

create trigger set_daily_summaries_updated_at
before update on public.daily_summaries
for each row execute function public.set_updated_at();

create trigger set_alert_events_updated_at
before update on public.alert_events
for each row execute function public.set_updated_at();

alter table public.families enable row level security;
alter table public.care_recipients enable row level security;
alter table public.family_contacts enable row level security;
alter table public.device_installations enable row level security;
alter table public.conversation_sessions enable row level security;
alter table public.session_connections enable row level security;
alter table public.conversation_turns enable row level security;
alter table public.turn_health_signals enable row level security;
alter table public.daily_summaries enable row level security;
alter table public.alert_events enable row level security;
