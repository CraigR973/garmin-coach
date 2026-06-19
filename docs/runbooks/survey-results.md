# Runbook: reading in-app survey results

Responses from the in-app "Week 1 pulse" survey land in two decoupled tables
(see `migrations/versions/033_survey_responses.py`):

- **`survey_responses`** — the de-identified answers (`answers` JSONB) + the
  auto-tagged `league_ids`. `contact_player_id` is `NULL` unless the player
  ticked "happy to be contacted".
- **`survey_completions`** — one row per `(player_id, survey_key)`, used only to
  stop the client re-prompting. **Never join it to `survey_responses`** — doing
  so would re-identify the anonymous answers and defeat the whole point.

`survey_key` for this survey is `week1_pulse`.

Run these in the Supabase SQL editor (or `psql`). Each is read-only.

## 1. Did everyone answer?

```sql
SELECT
  (SELECT count(*) FROM survey_responses   WHERE survey_key = 'week1_pulse') AS responses,
  (SELECT count(*) FROM survey_completions WHERE survey_key = 'week1_pulse') AS completions;
```

## 2. Overall rating (Q2, 1–5) distribution

```sql
SELECT (answers->>'q2_overall')::int AS rating, count(*)
FROM survey_responses
WHERE survey_key = 'week1_pulse'
GROUP BY 1 ORDER BY 1;
```

## 3. Choice questions (Q3–Q6) distribution

```sql
SELECT q, val, count(*)
FROM survey_responses,
LATERAL (VALUES
  ('q3_frequency',        answers->>'q3_frequency'),
  ('q4_notifications',    answers->>'q4_notifications'),
  ('q5_missed_deadline',  answers->>'q5_missed_deadline'),
  ('q6_biggest_annoyance',answers->>'q6_biggest_annoyance')
) AS t(q, val)
WHERE survey_key = 'week1_pulse'
GROUP BY q, val
ORDER BY q, count(*) DESC;
```

## 4. Per-league breakdown (the important cut)

Unnests `league_ids` so a response in N leagues counts toward each. Watch the
average rating per league — a league dragging low is your churn-risk signal.

```sql
SELECT l.name,
       count(*)                                      AS responses,
       round(avg((r.answers->>'q2_overall')::numeric), 2) AS avg_rating
FROM survey_responses r
CROSS JOIN LATERAL jsonb_array_elements_text(r.league_ids) AS lid
JOIN leagues l ON l.id = lid::uuid
WHERE r.survey_key = 'week1_pulse'
GROUP BY l.name
ORDER BY responses DESC;
```

## 5. Free-text: open feedback (Q7) + the Scotland bonus (Q9)

```sql
SELECT created_at,
       answers->>'q6_other'  AS annoyance_other,
       answers->>'q7_open'   AS feedback,
       answers->>'q9_scotland' AS scotland
FROM survey_responses
WHERE survey_key = 'week1_pulse'
  AND (answers->>'q7_open' IS NOT NULL
       OR answers->>'q9_scotland' IS NOT NULL
       OR answers->>'q6_other' IS NOT NULL)
ORDER BY created_at DESC;
```

## 6. Bug follow-ups (opted-in only)

The **only** query that ties a person to their answer — and only for those who
explicitly opted in via the contact checkbox.

```sql
SELECT p.display_name, p.email,
       r.answers->>'q6_biggest_annoyance' AS annoyance,
       r.answers->>'q7_open'              AS feedback,
       r.created_at
FROM survey_responses r
JOIN profiles p ON p.id = r.contact_player_id
WHERE r.survey_key = 'week1_pulse'
  AND r.contact_player_id IS NOT NULL
ORDER BY r.created_at DESC;
```
