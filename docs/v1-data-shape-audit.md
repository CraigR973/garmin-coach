# v1 data-shape audit

Source files inspected on 2026-06-20:

- Garmin: `~/garmin-spike/out/training_readiness.json`, `sleep.json`,
  `hrv.json`, `body_battery.json`, `activities.json`, `activity_details.json`,
  `activity_metric_channels.json`, `max_metrics_vo2.json`, `weigh_ins.json`.
- Hive: `~/garmin-spike/out_hive/getAll.json`, `getDevices.json`,
  `getProducts.json`.

## Stored shape decisions

- `profiles` remains the private auth/user table and now carries Garmin Coach
  user metadata: Garmin `userProfilePK`, Hive home id, timezone, and
  Kilmarnock coordinates. Public signup remains absent.
- `daily_metrics` is date-grained. It stores Training Readiness (`score`,
  `level`, `recoveryTime` as minutes), HRV summary (`weeklyAvg`,
  `lastNightAvg`, baseline band, status), body battery totals, RHR, weight, and
  VO2max, with `raw_payload` for source-specific fields.
- `sleep` is date-grained and maps Garmin `dailySleepDTO`: score, stage
  seconds, SpO2, respiration, RHR, sleep stress, restless moments, and sleep
  window UTC timestamps. Age-adjusted score is stored separately because it is
  an app rule, not a Garmin field.
- `activities` stores Garmin activity summaries keyed by `activityId`,
  including activity type/name, start/end UTC, duration/distance, power, HR,
  cadence, respiration, training effect/load, and recovery-exclusion flag for
  wrist-HR strength sessions.
- `activity_timeseries` follows `activity_details.json` descriptors. Dedicated
  columns cover `directPower`, `directHeartRate`, `directBikeCadence`,
  `directRespirationRate`, `directPerformanceCondition`,
  `directAvailableStamina`, and `directPotentialStamina`; raw descriptor-mapped
  metrics stay in JSONB.
- `temperature_readings` stores Hive heating product samples from
  `parsed[i].props.temperature`, keyed by source/product/time.
- `weather_daily` is date-grained for Open-Meteo Kilmarnock history/forecast:
  high/low, overnight low, wind in mph, precipitation, sunrise, and sunset.
- `manual_entries`, `plan_blocks`, `planned_workouts`, `analyses`,
  `experiments`, and `knowledge_base` are app-owned state. Structured JSONB is
  used where the product needs versioned and editable content before the exact
  UI shape settles.

## Sample fields that drove columns

- Training Readiness: `calendarDate`, `score`, `level`, `recoveryTime`,
  `sleepScore`, `acuteLoad`, `hrvWeeklyAverage`.
- Sleep: `dailySleepDTO.calendarDate`, `sleepStartTimestampGMT`,
  `sleepEndTimestampGMT`, `sleepTimeSeconds`, `deepSleepSeconds`,
  `lightSleepSeconds`, `remSleepSeconds`, `averageSpO2Value`,
  `averageRespirationValue`, `restlessMomentsCount`.
- Activity summary: `activityId`, `activityName`, `activityType.typeKey`,
  `beginTimestamp`, `endTimeGMT`, `duration`, `elapsedDuration`, `distance`,
  `avgPower`, `normPower`, `averageHR`, `averageBikingCadenceInRevPerMinute`,
  `avgRespirationRate`, `activityTrainingLoad`.
- Activity detail descriptors: `directPower`, `directHeartRate`,
  `directBikeCadence`, `directRespirationRate`,
  `directPerformanceCondition`, `directAvailableStamina`,
  `directPotentialStamina`, `directTimestamp`.
- Hive heating product: `id`, `type`, `lastSeen`, `props.temperature`,
  `state.target`.
