-- ADS: model-ready feature snapshot per (user_id, dt).
-- Combines "today" features from DWS with trailing 7-day rolling windows.
-- Input view : dws_user_ai_1d   (must include the 6 days BEFORE the target range)
-- Output     : ads_user_features_1d   partitioned by dt
--
-- RANGE windows over the day number (not ROWS) so that inactive days count as
-- gaps: "7d" always means 7 calendar days, not the last 7 active days.

WITH d AS (
    SELECT u.*, DATEDIFF(to_date(dt), DATE'1970-01-01') AS day_num
    FROM dws_user_ai_1d u
),

rolled AS (
    SELECT
        d.*,
        SUM(msgs)                       OVER w7 AS msgs_7d,
        COUNT(*)                        OVER w7 AS active_days_7d,
        SUM(sessions)                   OVER w7 AS sessions_7d,
        SUM(session_minutes)            OVER w7 AS session_minutes_7d,
        MAX(max_msgs_per_min)           OVER w7 AS max_msgs_per_min_7d,
        SUM(burst_minutes)              OVER w7 AS burst_minutes_7d,
        MAX(n_devices)                  OVER w7 AS max_devices_7d,
        MAX(n_tz)                       OVER w7 AS max_tz_7d,
        SUM(concurrent_device_minutes)  OVER w7 AS concurrent_device_minutes_7d,
        AVG(gap_cv)                     OVER w7 AS gap_cv_7d,
        -- msg-weighted shares over the window
        SUM(night_share * msgs)      OVER w7 / SUM(msgs) OVER w7 AS night_share_7d,
        SUM(reask_share * msgs)      OVER w7 / SUM(msgs) OVER w7 AS reask_share_7d,
        SUM(delegation_share * msgs) OVER w7 / SUM(msgs) OVER w7 AS delegation_share_7d,
        AVG(msg_len_std / NULLIF(msg_len_mean, 0)) OVER w7       AS msg_len_cv_7d,
        -- previous active day, for day-over-day change
        LAG(msgs) OVER (PARTITION BY user_id ORDER BY day_num)   AS prev_msgs
    FROM d
    WINDOW w7 AS (PARTITION BY user_id ORDER BY day_num RANGE BETWEEN 6 PRECEDING AND CURRENT ROW)
)

SELECT
    user_id,
    -- today
    msgs, sessions, session_minutes, max_session_minutes, max_session_msgs,
    max_msgs_per_min, p95_msgs_per_min, burst_minutes,
    n_platforms, n_devices, n_tz, concurrent_device_minutes,
    gap_mean_sec, gap_cv, hour_entropy, night_share, weekend_share,
    msg_len_mean, msg_len_std, code_share, question_share, reask_share, delegation_share,
    -- trailing 7d
    msgs_7d, active_days_7d, sessions_7d, session_minutes_7d,
    max_msgs_per_min_7d, burst_minutes_7d, max_devices_7d, max_tz_7d,
    concurrent_device_minutes_7d, gap_cv_7d, night_share_7d, reask_share_7d,
    delegation_share_7d, msg_len_cv_7d,
    -- trend
    msgs / NULLIF(msgs_7d / active_days_7d, 0)   AS msgs_vs_7d_avg,
    msgs / NULLIF(prev_msgs, 0)                  AS msgs_dod_ratio,
    msgs / NULLIF(sessions, 0)                   AS msgs_per_session,
    dt
FROM rolled
