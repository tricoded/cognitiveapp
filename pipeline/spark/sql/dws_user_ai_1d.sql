-- DWS: one row per (user_id, dt) with daily behavioural aggregates.
-- Input view : dwd_ai_events_di
-- Output     : dws_user_ai_1d   partitioned by dt

WITH per_minute AS (
    -- messages per wall-clock minute → burst / velocity features
    SELECT user_id, dt, event_minute, COUNT(*) AS msgs_in_minute
    FROM dwd_ai_events_di
    GROUP BY user_id, dt, event_minute
),

minute_stats AS (
    SELECT user_id, dt,
           MAX(msgs_in_minute)                              AS max_msgs_per_min,
           PERCENTILE_APPROX(msgs_in_minute, 0.95)          AS p95_msgs_per_min,
           SUM(CASE WHEN msgs_in_minute >= 10 THEN 1 ELSE 0 END) AS burst_minutes
    FROM per_minute
    GROUP BY user_id, dt
),

per_hour AS (
    SELECT user_id, dt, local_hour, COUNT(*) AS c
    FROM dwd_ai_events_di
    GROUP BY user_id, dt, local_hour
),

hour_entropy AS (
    -- Shannon entropy of the local-hour distribution (0 = all in one hour)
    SELECT user_id, dt,
           -SUM((c / tot) * LN(c / tot)) AS hour_entropy
    FROM (
        SELECT h.*, SUM(c) OVER (PARTITION BY user_id, dt) AS tot
        FROM per_hour h
    ) x
    GROUP BY user_id, dt
),

sessions AS (
    SELECT user_id, dt, session_key, device_id,
           MIN(event_ts) AS s_start,
           MAX(event_ts) AS s_end,
           COUNT(*)      AS s_msgs
    FROM dwd_ai_events_di
    GROUP BY user_id, dt, session_key, device_id
),

session_stats AS (
    SELECT user_id, dt,
           COUNT(*)                                                         AS sessions,
           SUM((unix_timestamp(s_end) - unix_timestamp(s_start)) / 60D)    AS session_minutes,
           MAX((unix_timestamp(s_end) - unix_timestamp(s_start)) / 60D)    AS max_session_minutes,
           MAX(s_msgs)                                                      AS max_session_msgs
    FROM sessions
    GROUP BY user_id, dt
),

device_overlap AS (
    -- Minutes during which two DIFFERENT devices of the same account were in a
    -- session at the same time. Normal users (phone + laptop) rarely overlap;
    -- shared accounts overlap a lot.
    SELECT a.user_id, a.dt,
           SUM(
             GREATEST(0,
               unix_timestamp(LEAST(a.s_end, b.s_end)) - unix_timestamp(GREATEST(a.s_start, b.s_start))
             ) / 60D
           ) AS concurrent_device_minutes
    FROM sessions a
    JOIN sessions b
      ON a.user_id = b.user_id
     AND a.dt = b.dt
     AND a.device_id < b.device_id
     AND a.s_start < b.s_end
     AND b.s_start < a.s_end
    GROUP BY a.user_id, a.dt
),

base AS (
    SELECT user_id, dt,
           COUNT(*)                                                         AS msgs,
           COUNT(DISTINCT platform)                                         AS n_platforms,
           COUNT(DISTINCT device_id)                                        AS n_devices,
           COUNT(DISTINCT tz_offset)                                        AS n_tz,
           AVG(gap_sec)                                                     AS gap_mean_sec,
           STDDEV_SAMP(gap_sec)                                             AS gap_std_sec,
           STDDEV_SAMP(gap_sec) / NULLIF(AVG(gap_sec), 0)                   AS gap_cv,
           AVG(CASE WHEN local_hour BETWEEN 0 AND 5 THEN 1D ELSE 0D END)  AS night_share,
           AVG(CASE WHEN local_dow IN (1, 7) THEN 1D ELSE 0D END)         AS weekend_share,
           AVG(msg_len)                                                     AS msg_len_mean,
           STDDEV_SAMP(msg_len)                                             AS msg_len_std,
           AVG(CAST(has_code AS DOUBLE))                                    AS code_share,
           AVG(CAST(is_question AS DOUBLE))                                 AS question_share,
           AVG(CAST(is_reask AS DOUBLE))                                    AS reask_share,
           AVG(CASE WHEN prompt_kind = 'delegation' THEN 1D ELSE 0D END)  AS delegation_share
    FROM dwd_ai_events_di
    GROUP BY user_id, dt
)

SELECT
    b.user_id,
    b.msgs,
    s.sessions,
    ROUND(s.session_minutes, 2)                   AS session_minutes,
    ROUND(s.max_session_minutes, 2)               AS max_session_minutes,
    s.max_session_msgs,
    m.max_msgs_per_min,
    m.p95_msgs_per_min,
    m.burst_minutes,
    b.n_platforms,
    b.n_devices,
    b.n_tz,
    COALESCE(ROUND(o.concurrent_device_minutes, 2), 0.0) AS concurrent_device_minutes,
    b.gap_mean_sec,
    b.gap_std_sec,
    b.gap_cv,
    h.hour_entropy,
    b.night_share,
    b.weekend_share,
    b.msg_len_mean,
    b.msg_len_std,
    b.code_share,
    b.question_share,
    b.reask_share,
    b.delegation_share,
    b.dt
FROM base b
JOIN session_stats s ON b.user_id = s.user_id AND b.dt = s.dt
JOIN minute_stats  m ON b.user_id = m.user_id AND b.dt = m.dt
JOIN hour_entropy  h ON b.user_id = h.user_id AND b.dt = h.dt
LEFT JOIN device_overlap o ON b.user_id = o.user_id AND b.dt = o.dt
