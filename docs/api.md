# JSON API (`/api/v1`)

Interactive, always-accurate docs are served at `/docs` (OpenAPI). All examples
below assume the demo server at `http://localhost:8000`.

## `POST /api/v1/grievances`
Create + classify + dispatch a grievance.

```bash
curl -s -X POST http://localhost:8000/api/v1/grievances \
  -H 'Content-Type: application/json' \
  -d '{"citizen_name":"Nirav Chauhan","citizen_phone":"9876500011",
       "citizen_district":"Surat","subject":"વીજ સમસ્યા",
       "body":"ટ્રાન્સફોર્મર બળી ગયું અને અંધારપટ છે પીજીવીસીએલ"}'
```
```json
{"ref_no":"SETU-20260805-XXXXXX","status":"ASSIGNED_L1","department":"ENERGY",
 "urgency":"NORMAL","confidence":0.71,"current_level":"L1",
 "created_at":"...","sla_due_at":"...","duplicate_of":null}
```

## `GET /api/v1/grievances/{ref_no}`
Return the current state of a grievance (404 if unknown).

## `POST /api/v1/classify`
Classify **without persisting** — ideal for demos. Returns the chosen
department, secondary departments, urgency, detected language, decided-by-stage,
degraded flag, provider, and the full lexical/semantic/fused score maps plus
per-stage latency.

```bash
curl -s -X POST http://localhost:8000/api/v1/classify \
  -H 'Content-Type: application/json' \
  -d '{"subject":"","body":"ખેડૂત ને યુરિયા ખાતર નથી"}'
```

## `GET /api/v1/departments`
List active departments (`code`, `name_en`, `name_gu`).

## `GET /api/v1/stats`
Totals and counts by status and by department.

## `GET /api/v1/health`
App/DB/provider status. Example:
```json
{"status":"ok","database":"ok","provider":{"name":"mock","healthy":true,"degraded":false}}
```

## Admin console (`/admin`)
HTTP Basic (`ADMIN_USERNAME` / `ADMIN_PASSWORD`). Pages: dashboard, grievances
(filter/sort/paginate), grievance detail + Decision Trace, review queue + active
learning, departments/keywords, officers, settings, analytics, evaluation.

## Officer actions (`/action/{token}`)
`GET` renders a confirmation page (never mutates). `POST` performs the single-use
action (resolve / forward / info). Expired/used/invalid tokens render a friendly
bilingual page.
