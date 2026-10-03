"""
Synthetic AI-usage event generator.

Produces raw event logs in the same shape the Chrome extension emits
(one row per prompt sent on an AI platform), for many users over many days,
partitioned Hive-style:  <out>/raw/events/dt=YYYY-MM-DD/part-0000.jsonl

Why synthetic? The real extension only has one user (me). To build and
evaluate a risk model we need a population with known ground truth, so we
simulate normal personas, inject labelled risky personas, and inject the kind
of data-quality defects real pipelines suffer from. Labels are written to a
separate location, like real risk labels (chargebacks, manual review) that
arrive separately and late.

Usage:
    python -m pipeline.simulator.generate_events --users 2000 --days 60
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PLATFORMS = ["chatgpt", "claude", "gemini", "deepseek", "perplexity"]
TZ_CHOICES = [8, 8, 8, 8, 9, 7, 0, 1, -5, -8]  # mostly UTC+8
CATEGORIES = ["coding", "writing", "study", "search", "other"]


# ─────────────────────────────────────────────────────────────────────────────
#  Personas
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Persona:
    name: str
    p_active: float            # probability of being active on a given day
    weekday_boost: float       # multiplier on p_active for Mon–Fri
    sessions: tuple            # (min, max) sessions per active day
    msgs: tuple                # (min, max) messages per session
    hours: tuple               # preferred local hours to start sessions
    gap_mu: float              # lognormal mu of seconds between prompts
    gap_sigma: float           # lognormal sigma (bots → tiny)
    msg_len_mu: float
    msg_len_sigma: float
    p_code: float
    p_question: float
    p_delegation: float        # "write it for me" vs "help me understand"
    p_reask: float


NORMAL = {
    "student":    Persona("student",    0.65, 1.1, (1, 3), (3, 18),  (14, 15, 16, 20, 21, 22), 4.2, 0.9, 4.3, 0.7, 0.15, 0.6, 0.45, 0.10),
    "developer":  Persona("developer",  0.75, 1.25, (1, 4), (4, 25), (9, 10, 11, 14, 15, 16, 17), 4.4, 0.8, 5.0, 0.9, 0.70, 0.4, 0.55, 0.08),
    "writer":     Persona("writer",     0.55, 1.0, (1, 2), (3, 12),  (7, 8, 9, 10, 11),         4.8, 0.7, 5.3, 0.6, 0.02, 0.3, 0.60, 0.05),
    "casual":     Persona("casual",     0.25, 0.9, (1, 1), (1, 6),   (12, 19, 20, 21, 22),      4.0, 1.0, 3.8, 0.8, 0.03, 0.7, 0.40, 0.05),
    # Heavy but legitimate users: the main source of false positives.
    "power_user": Persona("power_user", 0.90, 1.0, (3, 6), (15, 45), (1, 2, 9, 13, 18, 22, 23), 3.6, 0.7, 4.6, 0.9, 0.45, 0.45, 0.65, 0.15),
    # Night-owl researcher: long late sessions, re-asks while iterating. Looks scraper-ish, is legit.
    "night_owl":  Persona("night_owl",  0.70, 1.0, (1, 3), (10, 40), (0, 1, 2, 3, 23),          3.8, 0.6, 4.2, 0.6, 0.30, 0.5, 0.60, 0.25),
}
NORMAL_WEIGHTS = {"student": 0.33, "developer": 0.24, "writer": 0.12, "casual": 0.22, "power_user": 0.06, "night_owl": 0.03}

# Legitimate behaviours that mimic risk signals (the hard negatives):
P_TRAVELER = 0.06      # normal user whose time zone changes for a trip
P_FAMILY   = 0.04      # normal account legitimately shared in a household (overlapping devices)
LABEL_COVERAGE = 0.85  # share of risky users that ever get a label (the rest are undetected bads)

RISK = {
    # Scripted client hammering the platform with near-constant gaps.
    "bot":     Persona("bot",     0.95, 1.0, (4, 10), (40, 160), tuple(range(24)), 1.4, 0.10, 4.0, 0.15, 0.05, 0.2, 0.95, 0.02),
    # Account shared by 2–3 people: several devices / time zones, overlapping sessions.
    "shared":  Persona("shared",  0.85, 1.1, (3, 6), (4, 20), (9, 10, 14, 15, 20, 21, 22), 4.2, 0.9, 4.5, 0.8, 0.25, 0.5, 0.55, 0.08),
    # Bulk content extraction: long, night-time sessions, short templated prompts, many re-asks.
    "scraper": Persona("scraper", 0.80, 1.0, (1, 3), (30, 110), (1, 2, 3, 4, 5),  2.6, 0.35, 3.4, 0.25, 0.05, 0.3, 0.90, 0.45),
}
RISK_WEIGHTS = {"bot": 0.40, "shared": 0.35, "scraper": 0.25}


# ─────────────────────────────────────────────────────────────────────────────
#  Data-quality defects (the "incidents" the DQ layer must catch)
# ─────────────────────────────────────────────────────────────────────────────

def defect_plan(days: int) -> dict[int, str]:
    """day offset → defect kind. Scaled to the requested window."""
    at = lambda frac: int(days * frac)
    return {
        at(0.33): "duplicate_retry",     # extension retries on 5xx → dup event_ids
        at(0.55): "null_user_id",        # logged-out state sends events with no user
        at(0.68): "clock_skew",          # one platform's client_ts off by +1h (tz bug)
        at(0.83): "schema_drift",        # v1.1 renames msg_len → message_length
        at(0.92): "volume_drop",         # DOM selector change breaks deepseek tracking
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Generation
# ─────────────────────────────────────────────────────────────────────────────

def make_users(n: int, risk_rate: float, days: int, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    n_risk = int(round(n * risk_rate))
    normal_names = list(NORMAL_WEIGHTS)
    normal_p = np.array(list(NORMAL_WEIGHTS.values()))
    risk_names = list(RISK_WEIGHTS)
    risk_p = np.array(list(RISK_WEIGHTS.values()))

    for i in range(n):
        uid = f"u{i:06d}"
        is_risk = i < n_risk
        base = rng.choice(normal_names, p=normal_p / normal_p.sum())
        risk_type = rng.choice(risk_names, p=risk_p / risk_p.sum()) if is_risk else None
        # Risky behaviour starts part-way through; before onset they behave normally.
        onset = int(rng.integers(int(days * 0.1), int(days * 0.9))) if is_risk else None
        # Some risky users are camouflaged (weaker signal) so the task isn't trivial.
        stealth = float(rng.beta(2.0, 1.6)) * 0.95 if is_risk else 0.0
        n_devices = 1 + int(rng.random() < 0.25)  # phone + laptop is normal
        rows.append({
            "user_id": uid,
            "base_persona": base,
            "risk_type": risk_type,
            "onset_day": onset,
            "stealth": stealth,
            "tz": int(rng.choice(TZ_CHOICES)),
            "fav_platform": str(rng.choice(PLATFORMS, p=[0.40, 0.22, 0.13, 0.15, 0.10])),
            "n_devices": n_devices,
            # hard negatives only apply to normal users
            "traveler": (not is_risk) and rng.random() < P_TRAVELER,
            "family": (not is_risk) and rng.random() < P_FAMILY,
            "labelled": is_risk and rng.random() < LABEL_COVERAGE,
        })
    users = pd.DataFrame(rows)
    return users.sample(frac=1.0, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)


def _blend(normal: Persona, risk: Persona, stealth: float) -> Persona:
    """Interpolate risky persona toward the user's normal persona by `stealth`."""
    w = 1.0 - stealth
    lerp = lambda a, b: (1 - w) * a + w * b
    lerp_t = lambda a, b: (int(round(lerp(a[0], b[0]))), max(int(round(lerp(a[0], b[0]))), int(round(lerp(a[1], b[1])))))
    return Persona(
        name=risk.name,
        p_active=lerp(normal.p_active, risk.p_active),
        weekday_boost=lerp(normal.weekday_boost, risk.weekday_boost),
        sessions=lerp_t(normal.sessions, risk.sessions),
        msgs=lerp_t(normal.msgs, risk.msgs),
        hours=risk.hours if w > 0.5 else normal.hours + risk.hours,
        gap_mu=lerp(normal.gap_mu, risk.gap_mu),
        gap_sigma=lerp(normal.gap_sigma, risk.gap_sigma),
        msg_len_mu=lerp(normal.msg_len_mu, risk.msg_len_mu),
        msg_len_sigma=lerp(normal.msg_len_sigma, risk.msg_len_sigma),
        p_code=lerp(normal.p_code, risk.p_code),
        p_question=lerp(normal.p_question, risk.p_question),
        p_delegation=lerp(normal.p_delegation, risk.p_delegation),
        p_reask=lerp(normal.p_reask, risk.p_reask),
    )


def _sessions_for_day(user, persona: Persona, day_start_utc: datetime, rng, device_pool, tz_pool):
    """Yield event dicts for one user on one day."""
    n_sess = int(rng.integers(persona.sessions[0], persona.sessions[1] + 1))
    for _ in range(n_sess):
        tz = int(rng.choice(tz_pool))
        device = str(rng.choice(device_pool))
        local_hour = int(rng.choice(persona.hours))
        start = day_start_utc + timedelta(hours=local_hour - tz, seconds=int(rng.integers(0, 3600)))
        n_msgs = int(rng.integers(persona.msgs[0], persona.msgs[1] + 1))
        gaps = rng.lognormal(persona.gap_mu, persona.gap_sigma, size=n_msgs)
        gaps[0] = 0.0
        ts = start + pd.to_timedelta(np.cumsum(gaps), unit="s")
        platform = user["fav_platform"] if rng.random() < 0.75 else str(rng.choice(PLATFORMS))
        session_id = f"s{rng.integers(1 << 40):010x}"
        msg_len = np.clip(rng.lognormal(persona.msg_len_mu, persona.msg_len_sigma, size=n_msgs), 1, 20000).astype(int)
        has_code = rng.random(n_msgs) < persona.p_code
        is_question = rng.random(n_msgs) < persona.p_question
        is_reask = rng.random(n_msgs) < persona.p_reask
        delegation = rng.random(n_msgs) < persona.p_delegation
        # network latency: client_ts slightly before server receive ts
        latency = rng.exponential(0.25, size=n_msgs)
        for k in range(n_msgs):
            yield {
                "event_id": f"e{rng.integers(1 << 62):016x}",
                "user_id": user["user_id"],
                "device_id": device,
                "platform": platform,
                "event_type": "message_sent",
                "event_ts": ts[k].isoformat(),
                "client_ts": (ts[k] - timedelta(seconds=float(latency[k]))).isoformat(),
                "tz_offset": tz,
                "session_id": session_id,
                "msg_len": int(msg_len[k]),
                "has_code": bool(has_code[k]),
                "is_question": bool(is_question[k]),
                "is_reask": bool(is_reask[k]),
                "prompt_kind": "delegation" if delegation[k] else "learning",
                "category": "coding" if has_code[k] else str(rng.choice(CATEGORIES)),
                "app_version": "1.0.0",
            }


def generate(n_users: int, days: int, start: date, risk_rate: float, seed: int, out: Path) -> dict:
    rng = np.random.default_rng(seed)
    users = make_users(n_users, risk_rate, days, rng)
    defects = defect_plan(days)

    raw_dir = out / "raw" / "events"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)

    total = 0
    per_day = {}
    for d in range(days):
        dt = start + timedelta(days=d)
        day_start = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        weekday = dt.weekday() < 5
        events = []
        for user in users.to_dict("records"):
            normal = NORMAL[user["base_persona"]]
            risky_now = user["risk_type"] is not None and d >= user["onset_day"]
            persona = _blend(normal, RISK[user["risk_type"]], user["stealth"]) if risky_now else normal

            p = min(1.0, persona.p_active * (persona.weekday_boost if weekday else 1.0 / persona.weekday_boost))
            if rng.random() > p:
                continue

            uid_num = int(user["user_id"][1:])
            devices = [f"d{uid_num:06d}_{j}" for j in range(user["n_devices"])]
            tzs = [user["tz"]]
            other_tzs = [t for t in TZ_CHOICES if t != user["tz"]]
            if risky_now and user["risk_type"] == "shared":
                # 2–3 extra people on other devices; stealthier rings share within one region
                extra = 1 + int(rng.random() < 0.4)
                devices += [f"d{uid_num:06d}_x{j}" for j in range(extra)]
                if rng.random() > user["stealth"]:
                    tzs += list(rng.choice(other_tzs, size=extra))
            if user["family"]:
                # legit household sharing: extra device, same region
                devices.append(f"d{uid_num:06d}_fam")
            if user["traveler"] and (uid_num % days) <= d < (uid_num % days) + 7:
                # legit one-week trip in another time zone
                tzs = [int(rng.choice(other_tzs))] if rng.random() < 0.8 else tzs + [int(rng.choice(other_tzs))]
            events.extend(_sessions_for_day(user, persona, day_start, rng, devices, tzs))

        df = pd.DataFrame(events)
        defect = defects.get(d)
        if defect:
            df = inject_defect(df, defect, rng)

        part_dir = raw_dir / f"dt={dt.isoformat()}"
        part_dir.mkdir(parents=True, exist_ok=True)
        df.to_json(part_dir / "part-0000.jsonl", orient="records", lines=True)
        total += len(df)
        per_day[dt.isoformat()] = len(df)
        print(f"  dt={dt}  events={len(df):>7,}" + (f"   <- injected: {defect}" if defect else ""))

    # Labels arrive separately (like chargebacks / manual review outcomes).
    # Only LABEL_COVERAGE of risky users are ever caught and labelled; the rest
    # look like "normal" in training data, exactly as undetected fraud does.
    labels = users[users["risk_type"].notna() & users["labelled"]].copy()
    labels["onset_dt"] = labels["onset_day"].apply(lambda x: (start + timedelta(days=int(x))).isoformat())
    lab_dir = out / "raw" / "labels"
    lab_dir.mkdir(parents=True, exist_ok=True)
    labels[["user_id", "risk_type", "onset_dt", "stealth"]].to_csv(lab_dir / "risk_labels.csv", index=False)
    users.to_csv(lab_dir / "_simulator_users_truth.csv", index=False)

    manifest = {
        "n_users": n_users,
        "days": days,
        "start": start.isoformat(),
        "risk_rate": risk_rate,
        "seed": seed,
        "total_events": total,
        "injected_defects": {(start + timedelta(days=k)).isoformat(): v for k, v in defects.items()},
    }
    (out / "raw" / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def inject_defect(df: pd.DataFrame, kind: str, rng: np.random.Generator) -> pd.DataFrame:
    if df.empty:
        return df
    if kind == "duplicate_retry":
        dup = df.sample(frac=0.08, random_state=int(rng.integers(1 << 31)))
        return pd.concat([df, dup], ignore_index=True)
    if kind == "null_user_id":
        idx = df.sample(frac=0.05, random_state=int(rng.integers(1 << 31))).index
        df.loc[idx, "user_id"] = None
        return df
    if kind == "clock_skew":
        m = df["platform"] == "gemini"
        df.loc[m, "client_ts"] = (pd.to_datetime(df.loc[m, "client_ts"]) + pd.Timedelta(hours=1)).map(lambda t: t.isoformat())
        return df
    if kind == "schema_drift":
        df = df.rename(columns={"msg_len": "message_length"})
        df["app_version"] = "1.1.0"
        return df
    if kind == "volume_drop":
        m = df["platform"] == "deepseek"
        drop = df[m].sample(frac=0.85, random_state=int(rng.integers(1 << 31))).index
        return df.drop(index=drop)
    raise ValueError(kind)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--users", type=int, default=2000)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--start", type=str, default="2026-06-01")
    ap.add_argument("--risk-rate", type=float, default=0.04)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default="pipeline_data")
    a = ap.parse_args()
    print(f"Generating {a.users} users x {a.days} days -> {a.out}/raw/events")
    m = generate(a.users, a.days, date.fromisoformat(a.start), a.risk_rate, a.seed, Path(a.out))
    print(f"Done. {m['total_events']:,} events. Defects: {m['injected_defects']}")


if __name__ == "__main__":
    main()
