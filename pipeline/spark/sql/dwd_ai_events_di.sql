-- DWD: cleaned, deduplicated, sessionized AI-usage events (one row per prompt).
-- Input view : ods_ai_events      (typed raw events for the dt range)
-- Output     : dwd_ai_events_di   partitioned by dt
--
-- Cleaning rules (each one exists because a real incident needed it — see README):
--   1. Drop rows with NULL user_id           → they go to dwd_ai_events_quarantine instead
--   2. Deduplicate on event_id               → extension retries re-send the same event
--   3. Use server event_ts as the event time → client_ts is untrusted (clock skew)
--   4. Re-sessionize server-side             → 30-min inactivity gap OR device change starts a new session

WITH valid AS (
    SELECT *
    FROM ods_ai_events
    WHERE user_id IS NOT NULL
      AND event_ts IS NOT NULL
),

dedup AS (
    SELECT *
    FROM (
        SELECT v.*,
               ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY event_ts) AS rn
        FROM valid v
    ) t
    WHERE rn = 1
),

with_gap AS (
    SELECT d.*,
           unix_timestamp(event_ts)
             - unix_timestamp(LAG(event_ts) OVER (PARTITION BY user_id, device_id ORDER BY event_ts))
             AS gap_sec
    FROM dedup d
),

session_flag AS (
    SELECT w.*,
           CASE WHEN gap_sec IS NULL OR gap_sec > 1800 THEN 1 ELSE 0 END AS is_new_session
    FROM with_gap w
),

sessionized AS (
    SELECT s.*,
           SUM(is_new_session) OVER (
               PARTITION BY user_id, device_id ORDER BY event_ts
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS session_seq
    FROM session_flag s
)

SELECT
    event_id,
    user_id,
    device_id,
    platform,
    event_type,
    event_ts,
    client_ts,
    tz_offset,
    -- local wall-clock time of the user (for time-of-day features)
    event_ts + make_interval(0, 0, 0, 0, tz_offset, 0, 0)              AS local_ts,
    hour(event_ts + make_interval(0, 0, 0, 0, tz_offset, 0, 0))        AS local_hour,
    dayofweek(event_ts + make_interval(0, 0, 0, 0, tz_offset, 0, 0))   AS local_dow,
    date_trunc('MINUTE', event_ts)                                     AS event_minute,
    CASE WHEN is_new_session = 1 THEN NULL ELSE gap_sec END            AS gap_sec,
    concat(user_id, ':', device_id, ':', CAST(session_seq AS STRING))  AS session_key,
    msg_len,
    has_code,
    is_question,
    is_reask,
    prompt_kind,
    category,
    app_version,
    unix_timestamp(event_ts) - unix_timestamp(client_ts)               AS ingest_lag_sec,
    dt
FROM sessionized
