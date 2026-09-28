-- Silent-fallback metric (#109): how often an agent takes a structured
-- `companies_financials_retrieve` answer and then reads a filing body for the
-- SAME company anyway.
--
-- Why: #109 showed capable agents route around a wrong financials figure by
-- reading the annual report, and report the right answer without mentioning
-- the defect. Final-answer evals and error telemetry cannot see that. This
-- query makes the repair visible in the data we already log.
--
-- Run read-only against prod (users_mcptoolevent lives in the web DB):
--   cloud-sql-proxy + the alex_ro login, see the umbrella CLAUDE.md.
--
-- Columns per mcp_client_name (ROLLUP row = all clients):
--   financials_ok          successful, non-empty financials calls
--   same_company_fallback  followed within 30 min by the same user reading a
--                          filing of the same company        <- the tell
--   other_company_read     followed by a read of a DIFFERENT company <- baseline
--
-- Read same_company_fallback against other_company_read, never alone: agents
-- also read filings for context, and this query cannot tell a repair from a
-- legitimate follow-up read. A rise in the gap is the signal. The e2e probe
-- client (fr-e2e-probe) never falls back and should stay at 0 as a control.
--
-- Conversation matching: only `meta:openai/session` correlation ids span a
-- conversation. `mcp_session` ids are minted per request under the stateless
-- transport (measured 2026-09-28: 27,348 events, 27,348 ids), so matching on
-- them would zero the metric. Rows are split into two cohorts:
--   conversation_matched  both events carry the same openai session id
--   user_window           no stable id: same user within 30 min (can include
--                         an unrelated conversation, so it is looser)
-- Only successful, non-empty filing-body reads count. IDs are length-guarded
-- before the bigint cast (logged arguments are not range-checked).
--
-- Measured 2026-09-28, 30-day window (financials_ok / same-company / other):
--   all clients           2,608 / 419 (16.1%) / 247 (9.5%)
--   conversation_matched  1,417 / 197 (13.9%) / 114 (8.0%)
--   user_window           1,191 / 222 (18.6%) / 133 (11.2%); fr-e2e-probe 0 / 0
with f as (
  select user_id, timestamp ts, (arguments->>'id')::bigint company_id, mcp_client_name,
         case when correlation_source = 'meta:openai/session' then correlation_id end conv
  from users_mcptoolevent
  where name = 'companies_financials_retrieve' and status = 'ok' and has_data
    and timestamp > now() - interval '30 days' and user_id is not null
    and (arguments->>'id') ~ '^[0-9]{1,18}$'
), m as (
  select e.user_id, e.timestamp ts, fl.company_id,
         case when e.correlation_source = 'meta:openai/session' then e.correlation_id end conv
  from users_mcptoolevent e
  join filings_filing fl on fl.id = (e.arguments->>'filing_id')::bigint
  where e.name = 'filings_markdown_retrieve' and e.status = 'ok' and e.has_data
    and e.timestamp > now() - interval '30 days'
    and (e.arguments->>'filing_id') ~ '^[0-9]{1,18}$'
), j as (
  select f.*, case when f.conv is not null then 'conversation_matched' else 'user_window' end cohort,
    exists (select 1 from m where m.user_id = f.user_id and m.company_id = f.company_id
            and m.ts > f.ts and m.ts <= f.ts + interval '30 minutes'
            and (f.conv is null or m.conv = f.conv)) same_company,
    exists (select 1 from m where m.user_id = f.user_id and m.company_id <> f.company_id
            and m.ts > f.ts and m.ts <= f.ts + interval '30 minutes'
            and (f.conv is null or m.conv = f.conv)) other_company
  from f
)
select cohort, mcp_client_name, count(*) financials_ok,
       count(*) filter (where same_company) same_company_fallback,
       count(*) filter (where other_company) other_company_read
from j group by rollup(cohort, mcp_client_name) order by 1 nulls first, 3 desc;
