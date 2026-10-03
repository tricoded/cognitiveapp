# Feature dictionary

All features are computed in Spark SQL (`pipeline/spark/sql/`) at the grain **one row per `user_id` × `dt`**.
"Today" features come from `dws_user_ai_1d`. `_7d` features are trailing 7-calendar-day windows in
`ads_user_features_1d`. They use `RANGE BETWEEN 6 PRECEDING AND CURRENT ROW` over the day number, so
inactive days count as gaps. `ROWS` would silently mean "last 7 *active* days".

Time-of-day features use **local** time: `event_ts + tz_offset`. Event time is always the **server**
timestamp, because `client_ts` is untrusted (see the clock-skew incident in the README).

## Volume

| feature | definition | why it matters |
|---|---|---|
| `msgs` | prompts sent that day | base activity level |
| `sessions` | sessions, re-derived server-side (30-min gap or device change starts a new one) | client session ids can't be trusted |
| `session_minutes`, `max_session_minutes` | sum / max of (last − first prompt) per session | scrapers run very long sessions |
| `msgs_7d`, `active_days_7d`, `sessions_7d`, `session_minutes_7d` | 7-day sums / counts | stable baseline, less daily noise |
| `msgs_per_session` | `msgs / sessions` | bots pack many prompts into a session |

## Velocity / burst

| feature | definition | why it matters |
|---|---|---|
| `max_msgs_per_min` | max prompts in any wall-clock minute | people type; scripts don't need to |
| `p95_msgs_per_min` | `PERCENTILE_APPROX(msgs_in_minute, 0.95)` | robust to one lucky burst |
| `burst_minutes`, `burst_minutes_7d` | minutes with ≥ 10 prompts | sustained automation |
| `max_msgs_per_min_7d` | 7-day max | catches bots that are only active some days |

## Regularity

| feature | definition | why it matters |
|---|---|---|
| `gap_mean_sec` | mean seconds between consecutive prompts in a session (`LAG` window) | pace |
| `gap_cv`, `gap_cv_7d` | std / mean of those gaps | **bots ≈ 0** (metronome-like); humans are bursty, CV ≫ 0.5 |
| `msg_len_cv_7d` | CV of prompt length | templated prompts have near-constant length |

## Time pattern

| feature | definition | why it matters |
|---|---|---|
| `hour_entropy` | Shannon entropy of the local-hour distribution: `-Σ p·ln p` | round-the-clock automation has high entropy |
| `night_share`, `night_share_7d` | share of prompts 00:00–05:59 local; the 7d value is message-weighted | bulk extraction at night |
| `weekend_share` | share of prompts on Sat/Sun | persona signal (not risk by itself) |

## Diversity / account sharing

| feature | definition | why it matters |
|---|---|---|
| `n_devices`, `max_devices_7d` | distinct device ids | phone + laptop is normal; 3+ is unusual |
| `n_tz`, `max_tz_7d` | distinct UTC offsets | one person rarely spans time zones in a week |
| `concurrent_device_minutes(_7d)` | minutes where two *different* devices had **overlapping sessions**. Computed with a session self-join on interval overlap | the strongest sharing signal: one person can't type on two devices at once |
| `n_platforms` | distinct AI platforms | persona signal |

## Content (on-device features only; no prompt text)

| feature | definition | why it matters |
|---|---|---|
| `msg_len_mean`, `msg_len_std` | prompt length stats | templated scraping prompts are short and uniform |
| `code_share`, `question_share` | share with code / phrased as questions | persona signal |
| `reask_share`, `reask_share_7d` | share of prompts ≥ 50 % similar (Jaccard over word 3-shingle hashes) to the previous one | re-ask loops: scrapers iterate templates, humans "doom-prompt" |
| `delegation_share`, `delegation_share_7d` | share of "do it for me" prompts vs "help me understand" | the core CDI component |

## Trend

| feature | definition | why it matters |
|---|---|---|
| `msgs_vs_7d_avg` | today ÷ 7-day daily average | sudden change in behaviour (account takeover, onset of automation) |
| `msgs_dod_ratio` | today ÷ previous active day | same, shorter horizon |

## Cognitive Dependency Index (`ads_user_cdi_1d`)

`CDI = 100 × (0.35·delegation + 0.25·reask + 0.15·night + 0.25·intensity)`, where:
- `reask` is scaled so that 30 % of prompts saturates it
- `night` is scaled so that 50 % of prompts saturates it
- `intensity` is the population percentile of `session_minutes_7d` that day

Bands: ≥ 60 high, ≥ 40 medium. The weights live in one SQL file, so they are reviewed like any other
strategy parameter. The personal version (`app/personal_cdi.py`) uses AI minutes vs budget for
`intensity`, because a population of one has no percentile.

## Leakage checklist

- Labels (`raw/labels/risk_labels.csv`) are joined only at training time and are never used in features.
- A snapshot on `dt` uses only data up to `dt` (trailing windows, and `LAG` looks backwards only).
- Train, validation and test are split by **date**, not randomly, so the model is always evaluated on the future.
- IsolationForest is fit on train dates only; LightGBM early-stops on the validation dates, never the test dates.
