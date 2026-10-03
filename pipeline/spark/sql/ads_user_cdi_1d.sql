-- ADS: Cognitive Dependency Index (CDI) per (user_id, dt).
-- "Is this person's AI usage helping them or making them dependent?"
-- Input view : ads_user_features_1d
-- Output     : ads_user_cdi_1d   partitioned by dt
--
-- Components (all computed from on-device prompt features, never prompt text):
--   delegation   share of "do it for me" prompts vs "help me understand"   (7d)
--   reask        share of prompts that re-ask the previous one ("doom-prompting")
--   night        share of prompts sent 00:00–05:59 local time
--   intensity    percentile of 7d session minutes within the population that day
-- Each is in [0, 1]; CDI = 100 × weighted sum. Weights live here, in one place,
-- so they can be reviewed like any other risk strategy.

WITH comp AS (
    SELECT
        user_id,
        dt,
        COALESCE(delegation_share_7d, 0)                                              AS c_delegation,
        LEAST(1.0, COALESCE(reask_share_7d, 0) / 0.30)                                AS c_reask,
        LEAST(1.0, COALESCE(night_share_7d, 0) / 0.50)                                AS c_night,
        PERCENT_RANK() OVER (PARTITION BY dt ORDER BY session_minutes_7d)             AS c_intensity
    FROM ads_user_features_1d
)

SELECT
    user_id,
    ROUND(c_delegation, 4) AS c_delegation,
    ROUND(c_reask, 4)      AS c_reask,
    ROUND(c_night, 4)      AS c_night,
    ROUND(c_intensity, 4)  AS c_intensity,
    ROUND(100 * (0.35 * c_delegation + 0.25 * c_reask + 0.15 * c_night + 0.25 * c_intensity), 1) AS cdi,
    CASE
        WHEN 100 * (0.35 * c_delegation + 0.25 * c_reask + 0.15 * c_night + 0.25 * c_intensity) >= 60 THEN 'high'
        WHEN 100 * (0.35 * c_delegation + 0.25 * c_reask + 0.15 * c_night + 0.25 * c_intensity) >= 40 THEN 'medium'
        ELSE 'low'
    END AS cdi_band,
    dt
FROM comp
