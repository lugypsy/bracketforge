# app.py — BracketForge v6.1 (single file)
# Adds SB Points, Mag Points, and Grand Total breakdowns in Summary and Plan Details.

import io, csv
from typing import List, Dict, Tuple, Optional
import streamlit as st

try:
    import pandas as pd
except ImportError:
    pd = None

st.set_page_config(page_title="BracketForge", page_icon="⚔️", layout="wide")
st.title("⚔️ BracketForge — War Role Calculator (v6.1)")

# ----------------------------
# Built-in points matrix (levels 1–20)
# ----------------------------
LEVELS = list(range(1, 21))
MAG_POINTS = [300,330,365,400,440,485,535,590,650,715,785,865,950,1045,1150,1265,1390,1530,1685,1855]
SB_POINTS  = [700,850,1000,1150,1300,1450,1600,1750,1900,2050,2200,2300,2500,2650,2800,2950,3100,3250,3400,3550]
MAG_LOOKUP = {lvl: pts for lvl, pts in zip(LEVELS, MAG_POINTS)}
SB_LOOKUP  = {lvl: pts for lvl, pts in zip(LEVELS, SB_POINTS)}

def pts_mag(level) -> int:
    try: return MAG_LOOKUP.get(int(level), 0)
    except: return 0

def pts_sb(level) -> int:
    try: return SB_LOOKUP.get(int(level), 0)
    except: return 0

# ----------------------------
# Roles & energy
# ----------------------------
ROLE_DEFS = {
    "— Select —":         {"sb": 0, "mag": 0,  "energy_unit": 0},
    "SB-only (3 SB)":     {"sb": 3, "mag": 0,  "energy_unit": 7},   # per cast
    "1 SB + 7 Mag":       {"sb": 1, "mag": 7,  "energy_unit": 21},  # per unit
    "2 SB + 3 Mag":       {"sb": 2, "mag": 3,  "energy_unit": 20},  # per unit
    "Mag-only (10 Mag)":  {"sb": 0, "mag": 10, "energy_unit": 2},   # per cast
}

ROLES_ORDER = ["SB-only (3 SB)", "1 SB + 7 Mag", "2 SB + 3 Mag", "Mag-only (10 Mag)"]

# ----------------------------
# Sidebar: team & energy window
# ----------------------------
st.sidebar.header("Setup")

team_size = st.sidebar.number_input("How many players?", min_value=1, max_value=100, value=25, step=1)

duration_min = st.sidebar.number_input("Play window (minutes)", min_value=5, max_value=120, value=30, step=5)

regen_mode = st.sidebar.selectbox("Energy regen", ["Standard (1 per 3 min)", "GLW (1 per 1 min)", "Custom"], index=0)
if regen_mode == "Standard (1 per 3 min)":
    tick_minutes = 3
elif regen_mode == "GLW (1 per 1 min)":
    tick_minutes = 1
else:
    tick_minutes = st.sidebar.number_input("Custom: 1 energy every ... minutes", min_value=1, max_value=10, value=3, step=1)

energy_cap = st.sidebar.number_input("Energy cap per player", min_value=1, max_value=50, value=21, step=1)
start_energy = st.sidebar.number_input("Starting energy per player", min_value=0, max_value=50, value=21, step=1)

reserve_opener = st.sidebar.checkbox("Reserve 6× Mag for opener (kill from 16 HP)", value=True)

auto_clicked = st.sidebar.button("⚡ Auto-Assign Roles")

with st.sidebar.expander("Points matrix (built-in)", expanded=False):
    st.table({"Level": LEVELS, "Mag": MAG_POINTS, "SB": SB_POINTS})

# ----------------------------
# Roster I/O
# ----------------------------
def default_roster(n: int):
    return [{"name": f"Player {i}", "sb_level": 0, "mag_level": 0, "role": "— Select —"} for i in range(1, n+1)]

def normalize_rows(rows):
    norm = []
    for r in rows:
        name = str(r.get("name", "")).strip() or ""
        try: sb = int(r.get("sb_level", 0))
        except: sb = 0
        try: mag = int(r.get("mag_level", 0))
        except: mag = 0
        role = r.get("role", "— Select —")
        if role not in ROLE_DEFS: role = "— Select —"
        norm.append({"name": name, "sb_level": sb, "mag_level": mag, "role": role})
    return norm

st.subheader("Roster")
uploaded = st.file_uploader("Upload roster (CSV or Excel). Headers: name, sb_level, mag_level, role (role optional).", type=["csv", "xlsx"])

try:
    if uploaded:
        if uploaded.name.lower().endswith(".csv"):
            text = uploaded.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            raw = [row for row in reader]
            roster_in = normalize_rows(raw)
        else:
            import pandas as pd  # use if available
            df = pd.read_excel(uploaded)  # first sheet
            rename = {}
            for c in df.columns:
                lc = str(c).strip().lower()
                if lc in ("name","sb_level","mag_level","role"):
                    rename[c] = lc
            df = df.rename(columns=rename)
            for col in ["name","sb_level","mag_level"]:
                if col not in df.columns:
                    df[col] = "" if col=="name" else 0
            if "role" not in df.columns:
                df["role"] = "— Select —"
            raw = df[["name","sb_level","mag_level","role"]].to_dict("records")
            roster_in = normalize_rows(raw)
        team_size = len(roster_in)
        st.info(f"Detected team size from file: **{team_size}**")
    else:
        roster_in = default_roster(team_size)
except Exception as e:
    st.error(f"Failed to read file: {e}")
    roster_in = default_roster(team_size)

edited = st.data_editor(
    roster_in,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    column_config={
        "name":      st.column_config.TextColumn("Name", width="medium"),
        "sb_level":  st.column_config.NumberColumn("SB Level", min_value=0, max_value=20, step=1),
        "mag_level": st.column_config.NumberColumn("Mag Level", min_value=0, max_value=20, step=1),
        "role":      st.column_config.SelectboxColumn("Assigned Role", options=["— Select —"] + ROLES_ORDER),
    },
    key="roster_editor_v6_1",
)

# ----------------------------
# Energy window math
# ----------------------------
def spendable_energy_per_player(start: int, cap: int, duration_min: int, tick_minutes: int) -> int:
    base = min(start, cap)
    ticks = duration_min // tick_minutes
    return base + ticks

def role_casts_for_player(role: str, sb_level: int, mag_level: int, energy_spendable: int):
    if role == "SB-only (3 SB)":
        sb_casts = energy_spendable // 7
        return sb_casts, 0, sb_casts * pts_sb(sb_level), 0
    elif role == "Mag-only (10 Mag)":
        mag_casts = energy_spendable // 2
        return 0, mag_casts, 0, mag_casts * pts_mag(mag_level)
    elif role == "2 SB + 3 Mag":
        units = energy_spendable // 20
        sb_casts = 2 * units
        mag_casts = 3 * units
        return sb_casts, mag_casts, sb_casts * pts_sb(sb_level), mag_casts * pts_mag(mag_level)
    elif role == "1 SB + 7 Mag":
        units = energy_spendable // 21
        sb_casts = 1 * units
        mag_casts = 7 * units
        return sb_casts, mag_casts, sb_casts * pts_sb(sb_level), mag_casts * pts_mag(mag_level)
    else:
        return 0,0,0,0

# ----------------------------
# Auto-assign for this window
# ----------------------------
def auto_assign_window(rows, energy_spendable: int):
    new_rows = []
    for r in rows:
        candidates = []
        allowed = ROLES_ORDER if r["sb_level"] > 0 else ["Mag-only (10 Mag)"]
        for role in allowed:
            sb_casts, mag_casts, sb_pts, mag_pts = role_casts_for_player(role, r["sb_level"], r["mag_level"], energy_spendable)
            pts = sb_pts + mag_pts
            candidates.append((pts, sb_casts, mag_casts, role))
        best = max(candidates) if candidates else (0,0,0,"— Select —")
        new_rows.append({**r, "role": best[3]})
    return new_rows

energy_spendable = spendable_energy_per_player(start_energy, energy_cap, duration_min, tick_minutes)
if auto_clicked:
    edited = auto_assign_window(edited, energy_spendable)
    st.success(f"Auto-assigned roles for this {duration_min}m window (spendable energy per player ≈ {energy_spendable}).")

# ----------------------------
# Compute totals & cycles
# ----------------------------
def compute_totals(rows, energy_spendable: int, reserve_opener: bool):
    per = []
    total_sb_casts = total_mag_casts = 0
    total_sb_points = total_mag_points = 0
    for r in rows:
        sb_casts, mag_casts, sb_pts, mag_pts = role_casts_for_player(r["role"], r["sb_level"], r["mag_level"], energy_spendable)
        total_sb_casts += sb_casts
        total_mag_casts += mag_casts
        total_sb_points += sb_pts
        total_mag_points += mag_pts
        per.append({**r,
                    "sb_casts": sb_casts,
                    "mag_casts": mag_casts,
                    "pts_per_sb": pts_sb(r["sb_level"]),
                    "pts_per_mag": pts_mag(r["mag_level"]),
                    "sb_points": sb_pts,
                    "mag_points": mag_pts,
                    "player_points": sb_pts + mag_pts})
    opener_needed = 6 if reserve_opener else 0
    if total_mag_casts < opener_needed:
        cycles = 0
        leftover_mag = total_mag_casts
        sb_used_in_cycles = 0
    else:
        mag_after_opener = total_mag_casts - opener_needed
        cycles = min(total_sb_casts, mag_after_opener // 3)
        sb_used_in_cycles = cycles
        leftover_mag = mag_after_opener - 3*cycles

    sb_leftover = total_sb_casts - sb_used_in_cycles
    status = "OK" if cycles > 0 else "Insufficient Mag for opener" if reserve_opener and total_mag_casts < 6 else "No cycles possible"
    grand_total = total_sb_points + total_mag_points
    return per, total_sb_casts, total_mag_casts, total_sb_points, total_mag_points, grand_total, cycles, sb_leftover, leftover_mag, status

(per_rows, tot_sb_casts, tot_mag_casts,
 tot_sb_points, tot_mag_points, grand_total,
 cycles, sb_left, mag_left, status) = compute_totals(edited, energy_spendable, reserve_opener)

# ----------------------------
# Summary
# ----------------------------
st.subheader("Summary")
c1, c2, c3 = st.columns(3)
c1.metric("Spendable energy / player", energy_spendable)
c2.metric("Total SB casts", int(tot_sb_casts))
c3.metric("Total Mag casts", int(tot_mag_casts))

c4, c5, c6 = st.columns(3)
c4.metric("Cycles possible (SB + 3×Mag)", int(cycles))
c5.metric("SB leftover after cycles", int(sb_left))
c6.metric("Mag leftover after cycles", int(mag_left))

st.info(f"Status: {status}")

c7, c8, c9 = st.columns(3)
c7.metric("SB Points", int(tot_sb_points))
c8.metric("Mag Points", int(tot_mag_points))
c9.metric("Grand Total Points", int(grand_total))

st.caption("Cycles assume 6× Mag opener (toggle in sidebar). Each cycle consumes 1 SB + 3 Mag.")

st.divider()

# ----------------------------
# Plan Details
# ----------------------------
st.subheader("Plan Details")
plan_cols = ["name","sb_level","mag_level","role","pts_per_sb","pts_per_mag","sb_casts","mag_casts","sb_points","mag_points","player_points"]
st.dataframe([{k: r[k] for k in plan_cols} for r in per_rows], use_container_width=True, hide_index=True)

out = io.StringIO()
w = csv.DictWriter(out, fieldnames=plan_cols)
w.writeheader()
w.writerows([{k: r[k] for k in plan_cols} for r in per_rows])
st.download_button("Download Plan CSV", data=out.getvalue().encode("utf-8"),
                   file_name="bracketforge_plan_window.csv", mime="text/csv")

# ----------------------------
# Team Role Summary
# ----------------------------
st.divider()
st.subheader("Team Role Summary")
role_counts = {}
for r in edited:
    if r["role"] != "— Select —":
        role_counts[r["role"]] = role_counts.get(r["role"], 0) + 1

if role_counts:
    for role in ROLES_ORDER:
        if role in role_counts:
            st.markdown(f"- {role}: **{role_counts[role]}**")
    flat = ", ".join(f"{cnt} {role}" for role, cnt in role_counts.items())
    st.info(f"Assigned roles: {flat}.")
else:
    st.write("No roles assigned yet. Use Auto-Assign or pick roles manually.")
