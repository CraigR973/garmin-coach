-- Step 0 diagnosis for Mark's 2026-07-05 feedback.
-- Spec: docs/designs/coaching-calibration-and-data-truth.md
--
-- Purpose: prove whether the wrong *outputs* Mark saw are truthful reports of
-- wrong *inputs* (no plan loaded, shallow history, unclassified strength, stale
-- baselines/verdicts) before changing engine behaviour. Read-only — every
-- statement is a SELECT.
--
-- SCHEMA NOTE (verified against prod 2026-07-05): all app data lives in the
-- `coach` schema, NOT `public` (the public.profiles stub is empty). Every table
-- below is `coach.`-qualified so each block runs standalone. As of the diagnosis
-- there is a single profile (Mark), and history spans 2025-06-24 → present.
--
-- How to run: paste the whole file into the Supabase SQL editor (or via the
-- Supabase MCP execute_sql), or run one numbered section at a time — each block
-- is self-contained via a `WITH me AS (...)` CTE. If a second profile is ever
-- added, edit the `me` CTE to pick Mark, e.g.
--   SELECT id FROM coach.profiles WHERE display_name = 'Mark'

-- ===========================================================================
-- 0. Profiles (sanity — confirm which id the rest of the script targets)
-- ===========================================================================
SELECT id, display_name, role, timezone, created_at
FROM coach.profiles
ORDER BY created_at;

-- ===========================================================================
-- 1. Top-line data coverage  →  B1 "monthly/last-year data is wrong/missing"
--    How much history exists per source, and the date span. (2025-06-24 → now
--    at diagnosis: a full contiguous year, so "last year" is NOT a data gap.)
-- ===========================================================================
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT 'daily_metrics' AS source, count(*) AS rows,
       min(calendar_date) AS first_day, max(calendar_date) AS last_day,
       (max(calendar_date) - min(calendar_date) + 1) AS span_days
FROM coach.daily_metrics WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'sleep', count(*), min(calendar_date), max(calendar_date),
       (max(calendar_date) - min(calendar_date) + 1)
FROM coach.sleep WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'activities', count(*), min(start_utc::date), max(start_utc::date),
       (max(start_utc::date) - min(start_utc::date) + 1)
FROM coach.activities WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'weather_daily', count(*), min(calendar_date), max(calendar_date),
       (max(calendar_date) - min(calendar_date) + 1)
FROM coach.weather_daily WHERE user_id = (SELECT id FROM me);

-- ===========================================================================
-- 2. Monthly coverage of the metrics/sleep the reviews + trends aggregate  → B1
-- ===========================================================================
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT to_char(date_trunc('month', calendar_date), 'YYYY-MM') AS month,
       count(*) AS metric_days,
       count(*) FILTER (WHERE readiness_score IS NOT NULL) AS readiness_days,
       count(*) FILTER (WHERE hrv_last_night_avg_ms IS NOT NULL) AS hrv_days
FROM coach.daily_metrics WHERE user_id = (SELECT id FROM me)
GROUP BY 1 ORDER BY 1;

-- ===========================================================================
-- 3. Activity type mix, last 12 weeks  →  B2 "strength training has stopped"
--    (If strength_training is present, the brief's "stopped" is a narration
--    problem, not a classification gap.)
-- ===========================================================================
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT activity_type, count(*) AS sessions, max(start_utc::date) AS last_seen
FROM coach.activities
WHERE user_id = (SELECT id FROM me) AND start_utc >= now() - interval '84 days'
GROUP BY 1 ORDER BY 2 DESC;

-- ===========================================================================
-- 4. Plan loaded?  →  B2 "zero planned captured" + A3 rest-day pattern
--    NOTE: "captured" = adherence logged (manual_entries), which is separate
--    from whether a plan exists. Mark's plan exists; capture is ~0.
-- ===========================================================================
-- 4a. Active planned-workout totals + span.
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT count(*) AS active_planned, min(workout_date) AS first, max(workout_date) AS last
FROM coach.planned_workouts WHERE user_id = (SELECT id FROM me) AND is_active;

-- 4b. Active planned workouts by day-of-week  →  A3 (0-count days = rest days).
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT to_char(workout_date, 'Dy') AS dow, extract(isodow FROM workout_date) AS dow_num,
       count(*) AS planned
FROM coach.planned_workouts WHERE user_id = (SELECT id FROM me) AND is_active
GROUP BY 1, 2 ORDER BY 2;

-- ===========================================================================
-- 5. Baselines present?  →  A2. IMPORTANT: check whether `readiness_score` has
--    a row. If absent, the "76 is normal for me" fix and the soft-sleep override
--    have no personal readiness band to use — rebuild metric_baselines.
-- ===========================================================================
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT metric_key, source, sample_count,
       lower_quartile_value, median_value, mean_value, upper_quartile_value,
       window_start_date, window_end_date
FROM coach.metric_baselines WHERE user_id = (SELECT id FROM me)
ORDER BY metric_key;

-- ===========================================================================
-- 6. Verdict pattern + STALENESS  →  A1.
--    prompt_version tells you if the row was generated by the shipped fix.
--    softSleepRecoveryOverride null on every row = the fix has not run yet
--    (verdicts are not regenerated retroactively).
-- ===========================================================================
-- 6a. Verdict distribution, last 60 days.
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT verdict, count(*) AS days
FROM coach.analyses
WHERE user_id = (SELECT id FROM me) AND analysis_type = 'morning'
  AND subject_date >= (now()::date - 60)
GROUP BY 1 ORDER BY 2 DESC;

-- 6b. Recent mornings: was Amber driven by soft sleep while HRV/RHR were fine?
--     (Reproduces Mark's report; also shows prompt_version + whether the
--     batch-56 override fields are present.)
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT DISTINCT ON (subject_date)
       subject_date,
       verdict,
       prompt_version,
       context_packet->'verdict'->>'ageAdjustedSleepScore'     AS age_sleep,
       context_packet->'verdict'->>'hrvStatus'                 AS hrv_status,
       context_packet->'verdict'->>'hrvBelowBaseline'          AS hrv_below,
       context_packet->'verdict'->>'readinessLevel'            AS readiness_level,
       context_packet->'verdict'->>'softSleepRecoveryOverride' AS soft_override,
       context_packet->'verdict'->>'restingHeartRateWithinBaseline' AS rhr_in_band
FROM coach.analyses
WHERE user_id = (SELECT id FROM me) AND analysis_type = 'morning'
ORDER BY subject_date DESC, generated_at_utc DESC
LIMIT 21;

-- ===========================================================================
-- 7. Analysis inventory  →  C1. Confirms post_workout/post_strength/etc. ARE
--    generated (so "no post-workout feedback" is a visibility issue, not
--    generation) and lists every analysis_type + latest date.
-- ===========================================================================
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT analysis_type, count(*) AS rows, max(subject_date) AS latest
FROM coach.analyses WHERE user_id = (SELECT id FROM me)
GROUP BY 1 ORDER BY 2 DESC;

-- ===========================================================================
-- 8. Readiness distribution  →  A1/A2/#133. The soft-sleep override uses a
--    generic `readiness_score >= 70`; compare that to Mark's own distribution to
--    see whether normal-for-him readiness is being rejected. (Filter junk lows:
--    Garmin stores 0/1 when readiness is unavailable, which skews the quartiles.)
-- ===========================================================================
WITH me AS (SELECT id FROM coach.profiles ORDER BY created_at LIMIT 1)
SELECT count(*) AS n, min(readiness_score) AS min,
       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY readiness_score)::numeric,1) AS q1,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY readiness_score)::numeric,1) AS median,
       round(avg(readiness_score)::numeric,1) AS mean,
       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY readiness_score)::numeric,1) AS q3,
       max(readiness_score) AS max
FROM coach.daily_metrics
WHERE user_id = (SELECT id FROM me)
  AND readiness_score IS NOT NULL
  AND calendar_date >= (now()::date - 84);
