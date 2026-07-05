-- Step 0 diagnosis for Mark's 2026-07-05 feedback.
-- Spec: docs/designs/coaching-calibration-and-data-truth.md
--
-- Purpose: prove whether the wrong *outputs* Mark saw are truthful reports of
-- wrong *inputs* (no plan loaded, shallow history, unclassified strength) before
-- we change any engine code. Read-only — every statement is a SELECT.
--
-- How to run: paste the whole file into the Supabase SQL editor (or psql) against
-- PROD, or run one numbered section at a time (each block is self-contained via a
-- `WITH me AS (...)` CTE). If there is more than one profile, edit the `me` CTE in
-- each block to pick Mark, e.g. `SELECT id FROM profiles WHERE display_name = 'Mark'`.
-- Run section 0 first to see the profiles.

-- ===========================================================================
-- 0. Profiles (sanity — confirm which id the rest of the script targets)
-- ===========================================================================
SELECT id, display_name, timezone, created_at
FROM profiles
ORDER BY created_at;

-- ===========================================================================
-- 1. Top-line data coverage  →  B1 "monthly/last-year data is wrong/missing"
--    How much history exists per source, and the date span.
-- ===========================================================================
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT 'daily_metrics' AS source, count(*) AS rows,
       min(calendar_date) AS first_day, max(calendar_date) AS last_day,
       (max(calendar_date) - min(calendar_date) + 1) AS span_days
FROM daily_metrics WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'sleep', count(*), min(calendar_date), max(calendar_date),
       (max(calendar_date) - min(calendar_date) + 1)
FROM sleep WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'activities', count(*), min(start_utc::date), max(start_utc::date),
       (max(start_utc::date) - min(start_utc::date) + 1)
FROM activities WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'weather_daily', count(*), min(calendar_date), max(calendar_date),
       (max(calendar_date) - min(calendar_date) + 1)
FROM weather_daily WHERE user_id = (SELECT id FROM me)
UNION ALL
SELECT 'temperature_readings', count(*), min(captured_at_utc::date), max(captured_at_utc::date),
       (max(captured_at_utc::date) - min(captured_at_utc::date) + 1)
FROM temperature_readings WHERE user_id = (SELECT id FROM me);

-- ===========================================================================
-- 2. Monthly coverage of the metrics/sleep the reviews + trends aggregate
--    →  B1. Thin/missing months (esp. anything a year back) explain "wrong"
--    monthly reports and the empty year-on-year comparison.
-- ===========================================================================
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT to_char(date_trunc('month', calendar_date), 'YYYY-MM') AS month,
       count(*) AS metric_days,
       count(*) FILTER (WHERE readiness_score IS NOT NULL) AS readiness_days,
       count(*) FILTER (WHERE hrv_last_night_avg_ms IS NOT NULL) AS hrv_days,
       count(*) FILTER (WHERE resting_heart_rate_bpm IS NOT NULL) AS rhr_days
FROM daily_metrics WHERE user_id = (SELECT id FROM me)
GROUP BY 1 ORDER BY 1;

WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT to_char(date_trunc('month', calendar_date), 'YYYY-MM') AS month,
       count(*) AS sleep_nights,
       count(*) FILTER (WHERE score IS NOT NULL) AS scored_nights,
       count(*) FILTER (WHERE rem_sleep_sec IS NOT NULL) AS rem_nights,
       count(*) FILTER (WHERE deep_sleep_sec IS NOT NULL) AS deep_nights
FROM sleep WHERE user_id = (SELECT id FROM me)
GROUP BY 1 ORDER BY 1;

-- ===========================================================================
-- 3. Activity type mix, last 12 weeks  →  B2 "strength training has stopped"
--    If there is no strength_training row, the brief is telling the truth about
--    a classification/sync gap, not a real stop.
-- ===========================================================================
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT activity_type,
       count(*) AS sessions,
       max(start_utc::date) AS last_seen,
       count(*) FILTER (WHERE training_load IS NOT NULL) AS with_load
FROM activities
WHERE user_id = (SELECT id FROM me)
  AND start_utc >= now() - interval '84 days'
GROUP BY 1 ORDER BY 2 DESC;

-- ===========================================================================
-- 4. Is a plan loaded?  →  B2 "zero planned sessions" + A3 rest-day pattern
-- ===========================================================================
-- 4a. Active planned-workout totals + span.
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT count(*) AS active_planned_workouts,
       min(workout_date) AS first, max(workout_date) AS last
FROM planned_workouts
WHERE user_id = (SELECT id FROM me) AND is_active;

-- 4b. Active planned workouts per calendar month (what each monthly review sees).
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT to_char(date_trunc('month', workout_date), 'YYYY-MM') AS month,
       count(*) AS planned
FROM planned_workouts
WHERE user_id = (SELECT id FROM me) AND is_active
GROUP BY 1 ORDER BY 1;

-- 4c. Active planned workouts by day-of-week  →  A3. Days with 0 are the plan's
--     rest days. Confirm Mon & Fri read as rest (or that the table is empty).
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT to_char(workout_date, 'Dy') AS dow,
       extract(isodow FROM workout_date) AS dow_num,
       count(*) AS planned
FROM planned_workouts
WHERE user_id = (SELECT id FROM me) AND is_active
GROUP BY 1, 2 ORDER BY 2;

-- ===========================================================================
-- 5. Personal baselines present?  →  A2 fix input ("76 is good for me").
--    These mean/quartile bands are exactly what the review/trend packet should
--    carry so the narrative stops calling in-range numbers "eroding".
-- ===========================================================================
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT source, metric_key, sample_count,
       lower_quartile_value, mean_value, upper_quartile_value,
       window_start_date, window_end_date
FROM metric_baselines
WHERE user_id = (SELECT id FROM me)
ORDER BY source, metric_key;

-- ===========================================================================
-- 6. Verdict pattern  →  A1 over-caution ("Amber on sleep despite good HRV/RHR")
-- ===========================================================================
-- 6a. Verdict distribution, last 60 days.
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT verdict, count(*) AS days
FROM analyses
WHERE user_id = (SELECT id FROM me)
  AND analysis_type = 'morning'
  AND subject_date >= (now()::date - 60)
GROUP BY 1 ORDER BY 2 DESC;

-- 6b. Recent days: was Amber/Red driven by sleep while HRV was actually fine?
--     (Reproduces Mark's report straight from the stored verdict packets.)
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT subject_date,
       verdict,
       context_packet->'verdict'->>'ageAdjustedSleepScore' AS age_adj_sleep,
       context_packet->'verdict'->>'hrvStatus'             AS hrv_status,
       context_packet->'verdict'->>'hrvBelowBaseline'      AS hrv_below_baseline,
       context_packet->'verdict'->>'readinessLevel'        AS readiness_level,
       context_packet->'verdict'->>'subjectiveScore'       AS subjective
FROM analyses
WHERE user_id = (SELECT id FROM me)
  AND analysis_type = 'morning'
ORDER BY subject_date DESC
LIMIT 21;

-- ===========================================================================
-- 7. Analysis inventory  →  C1 "no post-workout feedback"
--    Confirms whether per-session (post_ride/strength/flexibility/walk) analyses
--    are actually being generated, and lists every analysis_type in use.
-- ===========================================================================
WITH me AS (SELECT id FROM profiles ORDER BY created_at LIMIT 1)
SELECT analysis_type, count(*) AS rows, max(subject_date) AS latest
FROM analyses
WHERE user_id = (SELECT id FROM me)
GROUP BY 1 ORDER BY 2 DESC;
