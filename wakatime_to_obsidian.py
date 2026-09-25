#!/usr/bin/env python3
"""
WakaTime -> Obsidian Daily Note Generator
=========================================
Перед первым запуском заполните блок НАСТРОЙКИ ниже (API-ключ WakaTime и
путь до вашего Obsidian vault) - без этого скрипт не запустится.

Запуск: python wakatime_to_obsidian.py
Или автоматически через cron каждый вечер:
  0 23 * * * /usr/bin/python3 /path/to/wakatime_to_obsidian.py

Зависимости: pip install requests
"""

import sys
import requests
from datetime import date, timedelta
from pathlib import Path

# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────
# Заполните эти два поля перед запуском:

WAKATIME_API_KEY = ""      # Ваш ключ: https://wakatime.com/settings/api-key
VAULT_PATH = ""            # Абсолютный путь до вашего Obsidian vault, например:
                            #   Windows: "C:\\Users\\User\\Documents\\MyVault"
                            #   macOS/Linux: "/home/user/Documents/MyVault"

DAILY_FOLDER = "daily"     # Папка для daily notes внутри vault
DATE_FORMAT = "%Y-%m-%d"   # Формат даты в именах файлов

# XP настройки
XP_PER_HOUR = 14          # XP за час кодинга
TOP_LANG_BONUS = 1.5      # Бонус XP за топ-язык дня (остальные языки × 1.0)
STREAK_BONUS_PER_DAY = 5  # Доп. XP за каждый день в стрике (макс × 3)
MIN_HOURS_FOR_STREAK = 1.0  # Минимум часов чтобы стрик не прервался

ACHIEVEMENT_THRESHOLDS = {
    "Deep Work": 6,
    "Highly Productive": 5,
    "Solid Session": 3,
    "Started": 1,
}

ACHIEVEMENT_HOUR_BONUS = {
    6: 40,   # Day Legend
    5: 25,   # Deep Work
    3: 15,   # Strong Session
    1: 5,    # Something Counts
}
ACHIEVEMENT_STREAK_BONUS = {
    30: 60,  # Month Streak
    14: 35,  # Two Weeks
    7:  20,  # Week Streak
    3:  10,  # Three Days
}
ACHIEVEMENT_MILESTONE_BONUS = {
    10000: 200,  # 10K XP Legend
    5000:  100,  # 5K XP Master
    1000:  50,   # 1K XP Veteran
}

WEEKLY_GOALS = {
    "top_lang_hours": 20,
    "total_hours": 30,
    "streak_days": 5,
}

# WAKATIME API

def get_wakatime_summary(target_date: date) -> dict:
    """Получает данные за конкретный день из WakaTime API."""
    date_str = target_date.strftime(DATE_FORMAT)
    url = "https://api.wakatime.com/api/v1/users/current/summaries"
    params = {"start": date_str, "end": date_str}
    headers = {"Authorization": f"Basic {_encode_key(WAKATIME_API_KEY)}"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [{}])[0] if data.get("data") else {}
    except requests.RequestException as e:
        print(f"⚠️  WakaTime API ошибка: {e}")
        return {}


def _encode_key(api_key: str) -> str:
    import base64
    return base64.b64encode(api_key.encode()).decode()


def parse_summary(summary: dict) -> dict:
    """Извлекает нужные поля из ответа WakaTime."""
    grand_total = summary.get("grand_total", {})
    total_seconds = grand_total.get("total_seconds", 0)
    total_hours = round(total_seconds / 3600, 2)

    languages_raw = {}
    for lang in summary.get("languages", []):
        name = lang.get("name", "Other")
        key = name.lower().replace(" ", "_").replace("+", "plus").replace("#", "sharp")
        hours = round(lang.get("total_seconds", 0) / 3600, 2)
        if hours > 0:
            languages_raw[key] = {"hours": hours, "display": name}

    if languages_raw:
        top_lang_key = max(languages_raw, key=lambda k: languages_raw[k]["hours"])
        top_lang_display = languages_raw[top_lang_key]["display"]
        top_lang_hours = languages_raw[top_lang_key]["hours"]
    else:
        top_lang_key = "other"
        top_lang_display = "Other"
        top_lang_hours = 0.0

    other_hours = round(total_hours - top_lang_hours, 2)

    return {
        "total_hours": total_hours,
        "top_lang": top_lang_display,
        "top_lang_key": top_lang_key,
        "top_lang_hours": top_lang_hours,
        "other_hours": max(other_hours, 0.0),
        "languages": {k: v["hours"] for k, v in languages_raw.items()},
    }

# ИСТОРИЯ ДЛЯ СТРИКА И XP

def load_all_daily_notes(vault: Path, folder: str) -> list[dict]:
    daily_path = vault / folder
    notes = []

    for md_file in sorted(daily_path.glob("*.md")):
        stem = md_file.stem
        try:
            d = date.fromisoformat(stem)
        except ValueError:
            continue

        file_content = md_file.read_text(encoding="utf-8")
        hours = _extract_field(file_content, "coding_time", float, 0.0)
        xp = _extract_field(file_content, "xp", int, 0)
        streak = _extract_field(file_content, "streak", int, 0)
        top_lang = _extract_field(file_content, "top_lang", str, "Other")
        top_lang_hours = _extract_field(file_content, "top_lang_hours", float, 0.0)
        notes.append({
            "date": d,
            "hours": hours,
            "xp": xp,
            "streak": streak,
            "top_lang": top_lang,
            "top_lang_hours": top_lang_hours,
        })

    return sorted(notes, key=lambda x: x["date"])


def _extract_field(content: str, field: str, cast, default):
    import re
    match = re.search(rf"^{field}::\s*(.+)$", content, re.MULTILINE)
    if match:
        try:
            return cast(match.group(1).strip())
        except (ValueError, TypeError):
            return default
    return default


def calculate_streak(history: list[dict], today: date, today_hours: float) -> int:
    """Считает текущий стрик"""
    all_days = {h["date"]: h["hours"] for h in history}
    all_days[today] = today_hours

    streak = 0
    check_date = today
    while True:
        hours = all_days.get(check_date, 0)
        if hours >= MIN_HOURS_FOR_STREAK:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break
    return streak


def get_best_streak(history: list[dict]) -> int:
    """Находит рекордный стрик за всё время"""
    if not history:
        return 0
    best = 0
    current = 0
    prev_date = None

    for entry in history:
        d = entry["date"]
        h = entry["hours"]
        if h >= MIN_HOURS_FOR_STREAK:
            if prev_date and (d - prev_date).days == 1:
                current += 1
            else:
                current = 1
            best = max(best, current)
        else:
            current = 0
        prev_date = d
    return best


def get_total_xp(history: list[dict]) -> int:
    return sum(h.get("xp", 0) for h in history)


def get_weekly_stats(history: list[dict], today: date) -> dict:
    """Агрегат за последние 7 дней (не считая сегодня)"""
    week_ago = today - timedelta(days=7)
    week = [h for h in history if week_ago <= h["date"] < today]
    return {
        "total_hours": round(sum(h.get("hours", 0) for h in week), 2),
        "days_coded": sum(1 for h in week if h.get("hours", 0) >= MIN_HOURS_FOR_STREAK),
        "total_xp": sum(h.get("xp", 0) for h in week),
    }


def _tier_bonus(value: float, table: dict[float, int]) -> int:
    """Бонус XP за наивысший порог в table, который прошло значение value"""
    for threshold in sorted(table.keys(), reverse=True):
        if value >= threshold:
            return table[threshold]
    return 0


def get_achievement_xp_bonus(total_hours: float, streak: int) -> int:
    """Суммарный бонус XP за дневные ачивки (часы + стрик), без учёта XP"""
    return (
        _tier_bonus(total_hours, ACHIEVEMENT_HOUR_BONUS)
        + _tier_bonus(streak, ACHIEVEMENT_STREAK_BONUS)
    )


def get_milestone_xp_bonus(total_xp_before: int, total_xp_after: int) -> int:
    """Разовый бонус, если сегодня пересечён порог общего XP (10K/5K/1K)"""
    for threshold in sorted(ACHIEVEMENT_MILESTONE_BONUS.keys(), reverse=True):
        if total_xp_before < threshold <= total_xp_after:
            return ACHIEVEMENT_MILESTONE_BONUS[threshold]
    return 0


def calculate_xp(top_lang_hours: float, other_hours: float, streak: int,
                  total_hours: float, total_xp_before: int) -> int:
    """Считает XP за день: база (часы × XP_PER_HOUR, топ-язык × TOP_LANG_BONUS,
    стрик-множитель) + бонусы за разблокированные сегодня ачивки (часы/стрик)
    + разовый бонус, если сегодня пересечена XP-веха (1K/5K/10K). Всё это
    засчитывается и в дневной xp::, и в общий счёт XP."""
    base_xp = top_lang_hours * XP_PER_HOUR * TOP_LANG_BONUS
    base_xp += other_hours * XP_PER_HOUR
    streak_bonus = min(streak, 3) * STREAK_BONUS_PER_DAY
    multiplier = 1.0 + (min(streak, 10) * 0.05)
    core_xp = int(base_xp * multiplier + streak_bonus)

    achievement_bonus = get_achievement_xp_bonus(total_hours, streak)
    total_before_milestone = total_xp_before + core_xp + achievement_bonus
    milestone_bonus = get_milestone_xp_bonus(total_xp_before, total_before_milestone)

    return core_xp + achievement_bonus + milestone_bonus


def get_history_top_lang(history: list[dict]) -> str:
    """Определяет топ-язык за всю историю по суммарным часам"""
    lang_totals: dict[str, float] = {}
    for entry in history:
        lang = entry.get("top_lang", "Other") or "Other"
        hours = entry.get("top_lang_hours", 0.0) or 0.0
        lang_totals[lang] = lang_totals.get(lang, 0.0) + hours
    if not lang_totals:
        return "Other"
    return max(lang_totals, key=lambda k: lang_totals[k])


def get_achievements(total_hours: float, streak: int, history: list[dict]) -> list[str]:
    """Возвращает список активных ачивок"""
    achievements = []

    for name, threshold in ACHIEVEMENT_THRESHOLDS.items():
        if total_hours >= threshold:
            achievements.append(name)
            break

    if streak >= 30:
        achievements.append("Month Streak")
    elif streak >= 14:
        achievements.append("Two Weeks Streak")
    elif streak >= 7:
        achievements.append("Week Streak")
    elif streak >= 3:
        achievements.append("Three Day Streak")

    total_xp = get_total_xp(history)
    if total_xp >= 10000:
        achievements.append("10K XP Legend")
    elif total_xp >= 5000:
        achievements.append("5K XP Master")
    elif total_xp >= 1000:
        achievements.append("1K XP Veteran")

    return achievements


def level_info(total_xp: int) -> tuple[int, int, int]:
    """Возвращает (level, xp_in_level, xp_needed_for_next)."""
    level = total_xp // 100
    xp_in_level = total_xp % 100
    xp_needed = 100
    return level, xp_in_level, xp_needed


def progress_bar(current: int, total: int, width: int = 20) -> str:
    filled = int(width * current / total) if total > 0 else 0
    bar = "▓" * filled + "░" * (width - filled)
    pct = int(100 * current / total) if total > 0 else 0
    return f"`{bar}` {pct}%"


def weekly_goal_bar(current: float, goal: float, label: str) -> str:
    pct = min(current / goal, 1.0) if goal > 0 else 0
    bar = progress_bar(int(pct * 100), 100, 15)
    return f"- {label}: {current} / {goal}  {bar}"

# ГЕНЕРАЦИЯ MARKDOWN

def render_note(
    today: date,
    parsed: dict,
    streak: int,
    best_streak: int,
    xp_today: int,
    total_xp: int,
    history: list[dict],
    weekly: dict,
    history_top_lang: str = "Other",
) -> str:

    note = f"""---
date: {today.strftime(DATE_FORMAT)}
tags: [daily, coding]
---

# Coding Day — {today.strftime('%d %B %Y')}

---

## WakaTime Data

date:: {today.strftime(DATE_FORMAT)}
coding_time:: {parsed['total_hours']}
top_lang:: {parsed['top_lang']}
top_lang_hours:: {parsed['top_lang_hours']}
other_hours:: {parsed['other_hours']}
xp:: {xp_today}
streak:: {streak}

---

## Today's Session

```dataviewjs
const h      = Number(dv.current().coding_time)    || 0;
const topH   = Number(dv.current().top_lang_hours) || 0;
const otherH = Number(dv.current().other_hours)    || 0;
const topLang = String(dv.current().top_lang || "Other");

const fmt = v => v > 0 ? v.toFixed(1) + "h" : "0h";

let status = "", pill = "";
if      (h >= 6) {{ status = "Legendary Day";     pill = "Legendary Session"; }}
else if (h >= 5) {{ status = "Highly Productive"; pill = "Blazing"; }}
else if (h >= 3) {{ status = "Strong Session";    pill = "Active Session"; }}
else if (h >= 1) {{ status = "Light Day";         pill = "Off To A Start"; }}
else if (h >  0) {{ status = "Just Started";      pill = "First Steps"; }}
else             {{ status = "Rest Day";          pill = "No Activity"; }}

const accentClr =
  h >= 6 ? "#a78bfa" :
  h >= 5 ? "#f97316" :
  h >= 3 ? "#3b82f6" :
  h >= 1 ? "#facc15" :
           "#334155";

const glowRgb =
  h >= 6 ? "139,92,246" :
  h >= 5 ? "249,115,22" :
  h >= 3 ? "37,99,235"  :
  h >= 1 ? "234,179,8"  :
           "51,65,85";

const steps = 8;
const sparkPoints = Array.from({{length: steps}}, (_, i) => {{
  const t = i / (steps - 1);
  return +(h * Math.pow(Math.sin(t * Math.PI / 2), 1.6)).toFixed(2);
}});
const maxSpark = Math.max(...sparkPoints, 0.1);

const W = 420, H = 90, padX = 8, padY = 8;
const pts = sparkPoints.map((v, i) => {{
  const x = padX + (i / (steps - 1)) * (W - padX * 2);
  const y = H - padY - ((v / maxSpark) * (H - padY * 2));
  return [x, y];
}});

function cubicPath(pts) {{
  if (pts.length < 2) return "";
  let d = `M ${{pts[0][0]}},${{pts[0][1]}}`;
  for (let i = 0; i < pts.length - 1; i++) {{
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[i + 1];
    const cx = (x0 + x1) / 2;
    d += ` C ${{cx}},${{y0}} ${{cx}},${{y1}} ${{x1}},${{y1}}`;
  }}
  return d;
}}

const linePath = cubicPath(pts);
const [lx, ly] = pts[pts.length - 1];
const areaPath = linePath
  + ` L ${{pts[pts.length-1][0]}},${{H - padY}}`
  + ` L ${{pts[0][0]}},${{H - padY}} Z`;

const sparkSVG = `
<svg width="${{W}}" height="${{H}}" viewBox="0 0 ${{W}} ${{H}}" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:${{H}}px">
  <defs>
    <linearGradient id="sGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${{accentClr}}" stop-opacity="0.28"/>
      <stop offset="100%" stop-color="${{accentClr}}" stop-opacity="0"/>
    </linearGradient>
    <filter id="ptGlow">
      <feGaussianBlur stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <path d="${{areaPath}}" fill="url(#sGrad)"/>
  <path d="${{linePath}}" fill="none" stroke="${{accentClr}}" stroke-width="2" stroke-opacity="0.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="${{linePath}}" fill="none" stroke="${{accentClr}}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="${{lx}}" cy="${{ly}}" r="8" fill="${{accentClr}}" opacity="0.18"/>
  <circle cx="${{lx}}" cy="${{ly}}" r="5" fill="${{accentClr}}" filter="url(#ptGlow)"/>
  <circle cx="${{lx}}" cy="${{ly}}" r="3" fill="#fff"/>
</svg>`;

const html = `
<div style="
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:linear-gradient(160deg,#070f1c 0%,#050a14 60%,#03060e 100%);
  border-radius:20px;
  padding:22px 22px 18px;
  position:relative;
  overflow:hidden;
  border:1px solid rgba(${{glowRgb}},0.2);
  box-shadow:0 0 50px rgba(${{glowRgb}},0.15), inset 0 0 60px rgba(${{glowRgb}},0.04);
  margin:4px 0;
">
  <div style="position:absolute;inset:0;pointer-events:none">
    <div style="
      position:absolute;inset:0;
      background-image:linear-gradient(rgba(${{glowRgb}},0.06) 1px,transparent 1px),linear-gradient(90deg,rgba(${{glowRgb}},0.06) 1px,transparent 1px);
      background-size:28px 28px;
      mask-image:linear-gradient(to top,rgba(0,0,0,0.7) 0%,transparent 55%);
      -webkit-mask-image:linear-gradient(to top,rgba(0,0,0,0.7) 0%,transparent 55%);
    "></div>
  </div>
  <div style="position:absolute;bottom:-20px;left:50%;transform:translateX(-50%);width:65%;height:50px;background:rgba(${{glowRgb}},0.3);filter:blur(25px);pointer-events:none"></div>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;position:relative">
    <span style="font-size:11px;color:rgba(148,163,184,0.6);letter-spacing:0.04em">WakaTime Data · Today</span>
    <span style="
      background:rgba(255,255,255,0.07);
      border:1px solid rgba(255,255,255,0.1);
      border-radius:20px;padding:3px 12px;
      font-size:11px;color:rgba(203,213,225,0.8);
    ">Daily</span>
  </div>
  <div style="position:relative;margin:0 -4px 14px">
    ${{sparkSVG}}
  </div>
  <div style="text-align:center;position:relative;margin-bottom:16px">
    <div style="font-size:11px;color:rgba(148,163,184,0.55);letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px">Coding Time</div>
    <div style="font-size:52px;font-weight:800;line-height:1;color:#fff;letter-spacing:-2px">
      ${{h > 0 ? h.toFixed(1) : "0"}}<span style="font-size:32px;font-weight:700;color:rgba(255,255,255,0.7)">h</span>
    </div>
    <div style="font-size:13px;color:rgba(148,163,184,0.6);margin-top:6px">${{status}}</div>
  </div>
  <div style="
    display:grid;grid-template-columns:1fr 1px 1fr;
    border-top:1px solid rgba(${{glowRgb}},0.15);
    padding-top:14px;margin-bottom:14px;position:relative;
  ">
    <div style="text-align:center;padding:0 8px">
      <div style="font-size:11px;color:rgba(148,163,184,0.5);letter-spacing:0.06em;text-transform:uppercase;margin-bottom:4px">${{topLang}}</div>
      <div style="font-size:22px;font-weight:700;color:#60a5fa;letter-spacing:-0.5px">${{fmt(topH)}}</div>
    </div>
    <div style="background:rgba(${{glowRgb}},0.2)"></div>
    <div style="text-align:center;padding:0 8px">
      <div style="font-size:11px;color:rgba(148,163,184,0.5);letter-spacing:0.06em;text-transform:uppercase;margin-bottom:4px">Other</div>
      <div style="font-size:22px;font-weight:700;color:rgba(203,213,225,0.65);letter-spacing:-0.5px">${{fmt(otherH)}}</div>
    </div>
  </div>
  <div style="display:flex;justify-content:center;position:relative">
    <div style="
      display:inline-flex;align-items:center;gap:7px;
      background:rgba(${{glowRgb}},0.1);
      border:1px solid rgba(${{glowRgb}},0.25);
      border-radius:20px;padding:5px 16px;
    ">
      <div style="width:6px;height:6px;border-radius:50%;background:${{accentClr}}"></div>
      <span style="font-size:12px;color:rgba(203,213,225,0.85)">${{pill}}</span>
    </div>
  </div>
</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## XP & Level

```dataviewjs
const pages = dv.pages('"daily"').where(p => p.xp != null).array();
const totalXP = pages.reduce((s, p) => s + (Number(p.xp) || 0), 0);
const todayXP = Number(dv.current().xp) || 0;
const level = Math.floor(totalXP / 100);
const xpInLevel = totalXP % 100;
const nextLevel = level + 1;
const xpLeft = 100 - xpInLevel;

function hexToRgb(hex) {{
  const v = hex.replace("#","");
  return [parseInt(v.slice(0,2),16), parseInt(v.slice(2,4),16), parseInt(v.slice(4,6),16)];
}}
function lerp(a,b,t) {{ return Math.round(a + (b-a)*t); }}
function levelColor(lv) {{
  const t = Math.min(Math.max(lv,0), 100) / 100;
  const from = hexToRgb("#4b5563");
  const to   = hexToRgb("#a855f7");
  return [lerp(from[0],to[0],t), lerp(from[1],to[1],t), lerp(from[2],to[2],t)];
}}
const [cr, cg, cb] = levelColor(level);
const clr     = `rgb(${{cr}},${{cg}},${{cb}})`;
const clrSoft = `rgba(${{cr}},${{cg}},${{cb}},0.4)`;
const clrGlow = `rgba(${{cr}},${{cg}},${{cb}},0.22)`;

const pct = xpInLevel; // 0–100, совпадает со шкалой 0/50/100
const labelInside = pct > 18;
const labelHtml = labelInside
  ? `<span style="position:absolute;top:50%;right:16px;transform:translateY(-50%);font-size:15px;font-weight:700;color:${{clr}}">${{pct}}%</span>`
  : `<span style="position:absolute;top:50%;left:calc(${{pct}}% + 14px);transform:translateY(-50%);font-size:15px;font-weight:700;color:rgba(230,230,238,0.85)">${{pct}}%</span>`;

const html = `
<div style="
  position:relative;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:rgba(22,22,28,0.55);
  backdrop-filter:blur(20px);
  -webkit-backdrop-filter:blur(20px);
  border:1px solid rgba(255,255,255,0.08);
  border-radius:22px;
  padding:24px 24px 26px;
  margin:14px 0 40px;
  box-shadow:0 10px 40px rgba(0,0,0,0.35);
  overflow:visible;
">
  <div style="position:absolute;left:50%;bottom:-30px;transform:translateX(-50%);width:72%;height:64px;background:${{clrGlow}};filter:blur(32px);pointer-events:none;z-index:0"></div>
  <div style="position:absolute;top:-24px;right:10%;width:120px;height:70px;background:${{clrGlow}};filter:blur(36px);pointer-events:none;z-index:0"></div>

  <div style="position:relative;display:flex;align-items:center;gap:9px;margin-bottom:14px">
    <svg width="15" height="15" viewBox="0 0 16 16" style="flex-shrink:0"><path d="M9 1 L3 9 H7 L6 15 L13 6 H9 Z" fill="${{clr}}"/></svg>
    <span style="font-size:13px;color:rgba(210,210,222,0.65);font-weight:500;letter-spacing:0.2px">Level ${{level}}</span>
  </div>

  <div style="position:relative;display:flex;align-items:baseline;gap:9px;margin-bottom:22px;flex-wrap:wrap">
    <span style="font-size:30px;font-weight:800;color:#f2f2f6;letter-spacing:-0.5px">${{xpInLevel}} XP</span>
    <span style="font-size:14px;color:rgba(210,210,222,0.4)">•</span>
    <span style="font-size:15px;color:rgba(210,210,222,0.6)">${{xpLeft}} XP to level ${{nextLevel}}</span>
  </div>

  <div style="position:relative;height:52px;border-radius:999px;border:1px solid rgba(255,255,255,0.12);overflow:visible">
    <div style="position:absolute;top:0;left:0;bottom:0;width:${{pct}}%;border-radius:999px;background:rgba(244,244,249,0.95);box-shadow:0 0 26px ${{clrSoft}};"></div>
    ${{labelHtml}}
  </div>

  <div style="position:relative;display:flex;justify-content:space-between;margin-top:9px;font-size:11px;color:rgba(210,210,222,0.4)">
    <span>0</span><span>50</span><span>100</span>
  </div>

  <div style="position:relative;display:flex;justify-content:space-between;margin-top:18px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.08);font-size:11px;color:rgba(210,210,222,0.5)">
    <span>Today: <strong style="color:${{clr}}">+${{todayXP}} XP</strong></span>
    <span>Total: <strong style="color:#e7e7ec">${{totalXP}} XP</strong></span>
  </div>
</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## Streak

```dataviewjs
const MIN_HOURS = {MIN_HOURS_FOR_STREAK};
const pages = dv.pages('"daily"').array();

function toDateStr(val) {{
  if (!val) return null;
  if (typeof val === "string") return val.slice(0, 10);
  if (val.toFormat) return val.toFormat("yyyy-MM-dd");
  if (val instanceof Date) return localDateStr(val);
  return String(val).slice(0, 10);
}}

function localDateStr(d) {{
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${{y}}-${{m}}-${{day}}`;
}}

pages.sort((a, b) => {{
  const da = toDateStr(a.date) || a.file.name;
  const db = toDateStr(b.date) || b.file.name;
  return da.localeCompare(db);
}});

const byDate = {{}};
for (const p of pages) {{
  const dateStr = toDateStr(p.date) || p.file.name;
  if (dateStr) byDate[dateStr] = Number(p.coding_time) || 0;
}}

const todayStr = toDateStr(dv.current().date) || (dv.current().file && dv.current().file.name);
const [ty, tm, td] = todayStr.split("-").map(Number);
const todayDate = new Date(ty, tm - 1, td);

function calcCurrentStreak() {{
  let streak = 0;
  let d = new Date(todayDate);
  while (true) {{
    const key = localDateStr(d);
    const h = byDate[key] || 0;
    if (h >= MIN_HOURS) {{
      streak++;
      d.setDate(d.getDate() - 1);
    }} else {{
      break;
    }}
  }}
  return streak;
}}

function calcBestStreak() {{
  let best = 0, cur = 0, prevMs = null;
  for (const p of pages) {{
    const dateStr = toDateStr(p.date) || p.file.name;
    if (!dateStr) continue;
    const h = Number(p.coding_time) || 0;
    const ms = new Date(dateStr + "T00:00:00").getTime();
    if (prevMs !== null) {{
      const diff = Math.round((ms - prevMs) / 86400000);
      if (diff === 1 && h >= MIN_HOURS) cur++;
      else cur = h >= MIN_HOURS ? 1 : 0;
    }} else {{
      cur = h >= MIN_HOURS ? 1 : 0;
    }}
    if (h >= MIN_HOURS) best = Math.max(best, cur);
    prevMs = ms;
  }}
  return best;
}}

const streak = calcCurrentStreak();
const bestStreak = Math.max(calcBestStreak(), streak);

const tier =
  streak >= 30 ? 4 :
  streak >= 14 ? 3 :
  streak >= 7  ? 2 :
  streak >= 3  ? 1 : 0;

const tierColor = ["#4b5563", "#facc15", "#ef4444", "#3b82f6", "#a78bfa"][tier];
const tierGlow  = ["transparent","rgba(250,204,21,0.45)","rgba(239,68,68,0.45)","rgba(59,130,246,0.45)","rgba(167,139,250,0.45)"][tier];
const tierLabel = ["No Streak","Warming Up","On Fire","In The Zone","Unstoppable"][tier];

const dayShort = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const now = todayDate;
const todayKey = todayStr;
const dow = (now.getDay() + 6) % 7; // 0 = Monday
const monday = new Date(now); monday.setDate(now.getDate() - dow);

const weekCells = dayShort.map((label, i) => {{
  const d = new Date(monday); d.setDate(monday.getDate() + i);
  const key = localDateStr(d);
  const h = byDate[key] || 0;
  const isFuture = key > todayKey;
  const met = h >= MIN_HOURS;
  const isToday = key === todayKey;
  return {{ label, hours: h, met, isFuture, isToday }};
}});

// Weekly hours goal
const weeklyGoal = {WEEKLY_GOALS['total_hours']};
const weekTotal = weekCells.filter(c => !c.isFuture).reduce((s,c) => s + c.hours, 0);
const weekPct = weeklyGoal > 0 ? Math.min(100, Math.round((weekTotal / weeklyGoal) * 100)) : 0;

const ringDash = Math.round((Math.min(streak, 30) / 30) * 94.2);
const sparkIcon = `
<svg width="34" height="34" viewBox="0 0 34 34" xmlns="http://www.w3.org/2000/svg">
  <circle cx="17" cy="17" r="15" fill="none" stroke="${{tierColor}}" stroke-width="2" opacity="0.3"/>
  <circle cx="17" cy="17" r="15" fill="none" stroke="${{tierColor}}" stroke-width="2"
    stroke-dasharray="${{ringDash}} 94.2" stroke-linecap="round"
    transform="rotate(-90 17 17)"/>
  <path d="M17 8 C13 13 12 17 15 20 C14 17 15 15 17 13 C19 16 20 18 18 21 C22 19 22 14 17 8 Z" fill="${{tierColor}}"/>
</svg>`;

let html = `
<div style="
  font-family:'SF Mono','Consolas',monospace;
  background:linear-gradient(160deg,#0d0d0f 0%,#08080a 100%);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:20px;
  padding:22px 22px 20px;
  color:#e5e5e5;
  box-shadow:0 0 40px rgba(0,0,0,0.4);
  margin:8px 0;
">

<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px">
  <div style="display:flex;align-items:center;gap:12px">
    ${{sparkIcon}}
    <div>
      <div style="font-size:11px;color:#8b8b93;letter-spacing:2px;font-weight:600">STREAK</div>
      <div style="display:flex;align-items:baseline;gap:6px">
        <span style="font-size:34px;font-weight:800;color:${{tierColor}};line-height:1;text-shadow:0 0 20px ${{tierGlow}}">${{streak}}</span>
        <span style="font-size:13px;color:#8b8b93;letter-spacing:1px">DAYS</span>
      </div>
    </div>
  </div>
  <div style="text-align:center;background:#151517;border:1px solid #232326;border-radius:12px;padding:8px 14px">
    <div style="font-size:9px;color:#6b6b73;letter-spacing:1.5px;margin-bottom:3px">BEST</div>
    <div style="font-size:18px;font-weight:700;color:#e5e5e5">${{bestStreak}}</div>
  </div>
</div>

<div style="height:1px;background:rgba(255,255,255,0.08);margin-bottom:18px"></div>

<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:8px;margin-bottom:20px">
  ${{weekCells.map(c => `
    <div style="display:flex;flex-direction:column;align-items:center;gap:8px">
      <div style="
        width:36px;height:36px;border-radius:50%;
        display:flex;align-items:center;justify-content:center;
        background:${{c.met ? tierColor : "#1c1c1f"}};
        border:${{c.isToday ? `1.5px solid ${{tierColor}}` : "1.5px solid transparent"}};
        box-shadow:${{c.met ? `0 0 12px ${{tierGlow}}` : "none"}};
      ">
        ${{c.met
          ? `<svg width="16" height="16" viewBox="0 0 16 16"><path d="M3 8.5 L6.5 12 L13 4" fill="none" stroke="#0a0a0a" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`
          : (c.isFuture ? "" : `<span style="font-size:10px;color:#4a4a52">-</span>`)
        }}
      </div>
      <span style="font-size:10px;color:${{c.isToday ? tierColor : "#6b6b73"}};letter-spacing:0.5px">${{c.label}}</span>
    </div>
  `).join("")}}
</div>

<div>
  <div style="font-size:10px;color:#8b8b93;letter-spacing:1.5px;margin-bottom:8px">WEEKLY HOURS</div>
  <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:8px">
    <span style="font-size:22px;font-weight:800;color:#e5e5e5">${{weekTotal.toFixed(1)}}</span>
    <span style="font-size:13px;color:#6b6b73">/ ${{weeklyGoal}}h</span>
    <span style="margin-left:auto;font-size:13px;color:${{tierColor}};font-weight:700">${{weekPct}}%</span>
  </div>
  <div style="background:#1c1c1f;border-radius:999px;height:10px;overflow:hidden">
    <div style="width:${{weekPct}}%;height:100%;border-radius:999px;background:${{tierColor}};box-shadow:0 0 10px ${{tierGlow}}"></div>
  </div>
</div>

<div style="display:flex;justify-content:space-between;margin-top:16px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#6b6b73">
  <span>Min for streak: <strong style="color:#a8a8b0">${{MIN_HOURS}}h</strong></span>
  <span>Status: <strong style="color:${{tierColor}}">${{tierLabel}}</strong></span>
</div>

</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## Weekly Goals

```dataviewjs
const GOALS = {{ top_lang_hours: {WEEKLY_GOALS['top_lang_hours']}, total_hours: {WEEKLY_GOALS['total_hours']}, active_days: {WEEKLY_GOALS['streak_days']} }};
const MIN_H = {MIN_HOURS_FOR_STREAK};

function toDateStr(v) {{ return String(v).slice(0, 10); }}
function toD(v) {{ return new Date(toDateStr(v) + "T00:00:00"); }}

const todayStr = toDateStr(dv.current().date) || (dv.current().file && dv.current().file.name);
const todayDate = toD(todayStr);
const dow = (todayDate.getDay() + 6) % 7; // 0 = Monday
const monday = new Date(todayDate); monday.setDate(todayDate.getDate() - dow);
const prevMonday = new Date(monday); prevMonday.setDate(monday.getDate() - 7);

const allPages = dv.pages('"daily"').where(p => p.date != null).array();
const pages     = allPages.filter(p => {{ const d = toD(p.date); return d >= monday && d <= todayDate; }});
const prevPages = allPages.filter(p => {{ const d = toD(p.date); return d >= prevMonday && d < monday; }});

const totalH     = pages.reduce((s,p) => s + (Number(p.coding_time)||0), 0);
const totalHPrev = prevPages.reduce((s,p) => s + (Number(p.coding_time)||0), 0);
const activeDays = pages.filter(p => (Number(p.coding_time)||0) >= MIN_H).length;
const totalXP    = pages.reduce((s,p) => s + (Number(p.xp)||0), 0);

const deltaPct = totalHPrev > 0
  ? Math.round(((totalH - totalHPrev) / totalHPrev) * 100)
  : (totalH > 0 ? 100 : 0);
const deltaUp = deltaPct >= 0;

// Топ-язык недели по суммарным часам top_lang_hours
const langWeekTotals = {{}};
for (const p of pages) {{
  const lang = String(p.top_lang || "Other");
  langWeekTotals[lang] = (langWeekTotals[lang] || 0) + (Number(p.top_lang_hours) || 0);
}}
const weekTopLang  = Object.keys(langWeekTotals).length
  ? Object.keys(langWeekTotals).reduce((a,b) => langWeekTotals[a]>langWeekTotals[b]?a:b)
  : "Other";
const weekTopLangH = langWeekTotals[weekTopLang] || 0;

const COLORS = {{
  lang:  {{ c:"#ef4444", l:"#fca5a5" }},
  hours: {{ c:"#f43f5e", l:"#fda4af" }},
  days:  {{ c:"#f97316", l:"#fdba74" }},
}};

function emoji(code, size) {{
  const s = size || 26;
  return `<img src="https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-160/${{code}}.png" width="${{s}}" height="${{s}}" style="display:block" alt=""/>`;
}}

const goals = [
  {{ key:"lang",  code:"1f48e", current:weekTopLangH, goal:GOALS.top_lang_hours, label:weekTopLang,    unit:"h", showDelta:false }},
  {{ key:"hours", code:"26a1",  current:totalH,       goal:GOALS.total_hours,    label:"Total Coding", unit:"h", showDelta:true  }},
  {{ key:"days",  code:"1f525", current:activeDays,   goal:GOALS.active_days,    label:"Active Days",  unit:"d", showDelta:false }},
];

function statusFor(pct) {{
  if (pct >= 1)    return {{ text:"COMPLETE",     bg:"#dc2626", fg:"#ffffff", glow:"rgba(220,38,38,0.55)" }};
  if (pct >= 0.85) return {{ text:"ALMOST THERE", bg:"#e11d48", fg:"#ffffff", glow:"rgba(225,29,72,0.5)" }};
  if (pct >= 0.5)  return {{ text:"ON TRACK",     bg:"#f97316", fg:"#ffffff", glow:"rgba(249,115,22,0.5)" }};
  if (pct >= 0.2)  return {{ text:"IN PROGRESS",  bg:"#c2410c", fg:"#ffffff", glow:"rgba(194,65,12,0.45)" }};
  return                 {{ text:"JUST STARTED",  bg:"#57534e", fg:"#e7e5e4", glow:"rgba(87,83,78,0.25)" }};
}}

function fmtNum(v) {{ return Number.isInteger(v) ? String(v) : v.toFixed(1); }}

let html = `
<div style="
  position:relative;
  border-radius:26px;
  overflow:hidden;
  margin:10px 0;
  background:#0a0506;
  box-shadow:0 24px 60px rgba(0,0,0,0.55);
">
  <div style="
    position:absolute;inset:-25%;
    filter:blur(65px);
    opacity:0.95;
    background:
      radial-gradient(circle at 18% 22%, #5c2328 0%, transparent 42%),
      radial-gradient(circle at 88% 12%, #2a1316 0%, transparent 48%),
      radial-gradient(circle at 78% 88%, #6b2a30 0%, transparent 42%),
      radial-gradient(circle at 15% 85%, #1a0d0f 0%, transparent 50%),
      linear-gradient(135deg, #2b1416 0%, #0a0506 100%);
    pointer-events:none;
  "></div>
  <div style="
    position:absolute;inset:0;
    background:linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,0.45) 100%);
    pointer-events:none;
  "></div>

  <div style="position:relative;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px">`;

html += `
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
  <div>
    <div style="font-size:21px;font-weight:700;color:#f9f1f1;letter-spacing:-0.2px">Weekly Goals</div>
    <div style="font-size:14px;color:#b09d9d;margin-top:3px">Progress this week (Mon–Sun)</div>
  </div>
  <div style="
    background:rgba(255,110,110,0.09);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
    border:1px solid rgba(255,140,140,0.16);
    border-radius:999px;padding:7px 15px;font-size:12px;color:#e8d9d9;
    letter-spacing:0.5px;font-weight:600;white-space:nowrap;
  ">THIS WEEK</div>
</div>`;

const deltaClr  = deltaUp ? "#fb7185" : "#9f6060";
const deltaSign = deltaUp ? "↑" : "↓";
html += `
<div style="display:flex;gap:10px;margin-bottom:18px">
  <div style="
    flex:1;background:rgba(255,110,110,0.06);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
    border:1px solid rgba(255,140,140,0.14);border-radius:18px;padding:16px 18px;
    box-shadow:0 8px 20px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.07);
  ">
    <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#b09d9d;letter-spacing:.6px;font-weight:600;font-family:'SF Mono','Consolas',monospace">${{emoji("26a1",13)}} HOURS CODED</div>
    <div style="font-size:28px;font-weight:800;color:#f9f1f1;margin-top:6px">${{totalH.toFixed(1)}}<span style="font-size:15px;color:#b09d9d;font-weight:600">h</span></div>
    <div style="font-size:12px;color:${{deltaClr}};margin-top:5px;font-weight:700">${{deltaSign}} ${{Math.abs(deltaPct)}}% vs last week</div>
  </div>
  <div style="
    flex:1;background:rgba(255,110,110,0.06);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
    border:1px solid rgba(255,140,140,0.14);border-radius:18px;padding:16px 18px;
    box-shadow:0 8px 20px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.07);
  ">
    <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#b09d9d;letter-spacing:.6px;font-weight:600;font-family:'SF Mono','Consolas',monospace">${{emoji("2728",13)}} TOTAL XP</div>
    <div style="font-size:28px;font-weight:800;color:#f9f1f1;margin-top:6px">${{totalXP}}</div>
    <div style="font-size:12px;color:#b09d9d;margin-top:5px">${{activeDays}} active day${{activeDays===1?"":"s"}}</div>
  </div>
</div>`;

html += `<div>`;
goals.forEach((g, i) => {{
  const col = COLORS[g.key];
  const pct = g.goal > 0 ? Math.min(g.current / g.goal, 1) : 0;
  const w   = Math.round(pct * 100);
  const st  = statusFor(pct);

  html += `
  <div style="
    background:rgba(255,110,110,0.055);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
    border:1px solid rgba(255,140,140,0.14);
    border-radius:20px;
    padding:18px 20px;
    margin-bottom:${{i < goals.length-1 ? "10px" : "0"}};
    box-shadow:0 10px 24px rgba(0,0,0,0.32), inset 0 1px 0 rgba(255,255,255,0.07);
  ">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:12px">
        <div style="
          width:42px;height:42px;border-radius:13px;flex-shrink:0;
          background:rgba(255,110,110,0.08);border:1px solid ${{col.c}}40;
          display:flex;align-items:center;justify-content:center;
          box-shadow:0 0 16px ${{col.c}}33;
        ">${{emoji(g.code, 24)}}</div>
        <span style="font-size:16px;font-weight:600;color:#f5eaea">${{g.label}}</span>
      </div>
      <span style="
        font-size:11px;font-weight:700;letter-spacing:.5px;
        padding:6px 14px;border-radius:999px;
        background:${{st.bg}};color:${{st.fg}};
        box-shadow:0 0 14px ${{st.glow}};
        white-space:nowrap;
      ">${{st.text}}</span>
    </div>

    <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:14px">
      <div>
        <div style="font-size:10.5px;color:#a3908f;letter-spacing:1px;font-family:'SF Mono','Consolas',monospace;margin-bottom:5px">PROGRESS</div>
        <div style="display:flex;align-items:baseline;gap:9px">
          <span style="font-size:38px;font-weight:800;color:#f9f1f1;letter-spacing:-1px">${{w}}%</span>
          ${{g.showDelta ? `<span style="font-size:14px;font-weight:700;color:${{deltaClr}}">${{deltaSign}}${{Math.abs(deltaPct)}}%</span>` : ""}}
        </div>
      </div>
      <div style="text-align:right">
        <div style="font-size:10.5px;color:#a3908f;letter-spacing:1px;font-family:'SF Mono','Consolas',monospace;margin-bottom:5px">CURRENT</div>
        <div style="font-size:20px;font-weight:700;color:#eee0e0">${{fmtNum(g.current)}}<span style="font-size:12.5px;color:#a3908f"> / ${{g.goal}}${{g.unit}}</span></div>
      </div>
    </div>

    <div style="position:relative;height:11px;border-radius:999px;overflow:hidden;background:repeating-linear-gradient(90deg, rgba(255,170,170,0.16) 0 3px, transparent 3px 7px)">
      <div style="position:absolute;top:0;left:0;height:100%;width:${{w}}%;border-radius:999px;background:linear-gradient(90deg, ${{col.l}}, ${{col.c}});box-shadow:0 0 12px ${{col.c}}bb, inset 0 1px 0 rgba(255,255,255,0.4)"></div>
    </div>
    <div style="display:flex;justify-content:space-between;margin-top:7px;font-size:10.5px;color:#8a7676;font-family:'SF Mono','Consolas',monospace;letter-spacing:.3px">
      <span>0%</span><span>50%</span><span>100%</span>
    </div>
  </div>`;
}});
html += `</div>`;

html += `
<div style="margin-top:18px;padding-top:16px;border-top:1px solid rgba(255,140,140,0.14)">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:11px">
    <div style="display:flex;gap:7px">
      ${{goals.map(g => `<div style="width:30px;height:30px;border-radius:10px;background:rgba(255,110,110,0.08);border:1px solid rgba(255,140,140,0.14);display:flex;align-items:center;justify-content:center">${{emoji(g.code, 18)}}</div>`).join("")}}
    </div>
    <div style="
      background:rgba(255,110,110,0.09);border:1px solid rgba(255,140,140,0.16);
      border-radius:999px;padding:6px 14px;font-size:11.5px;color:#e8d9d9;font-weight:600;
      letter-spacing:.4px;font-family:'SF Mono','Consolas',monospace;white-space:nowrap;
    ">${{goals.length}} GOALS</div>
  </div>
  <div style="text-align:center;font-size:11px;color:#8a7676;letter-spacing:.3px">Coding Progression System</div>
</div>`;

html += `</div></div>`;

const container = dv.el("div", "");
container.innerHTML = html;

```

---

## Today's Achievements

```dataviewjs
const h        = Number(dv.current().coding_time) || 0;
const streak   = Number(dv.current().streak)      || 0;
const todayXP  = Number(dv.current().xp)           || 0;

function dstr(v) {{ return String(v).slice(0,10); }}
const todayStr = dstr(dv.current().date);

const allPages  = dv.pages('"daily"').where(p => p.xp != null && p.date != null).array();

const totalXPBefore = allPages
  .filter(p => dstr(p.date) < todayStr)
  .reduce((s,p) => s + (Number(p.xp)||0), 0);
const totalXP = totalXPBefore + todayXP;

// Apple emoji (real bitmap set), fetched by unicode codepoint
function emoji(code, size) {{
  const s = size || 26;
  return `<img src="https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-160/${{code}}.png" width="${{s}}" height="${{s}}" style="display:block" alt=""/>`;
}}

const HOUR_TIERS = [
  {{ min:6, name:"Day Legend",      desc:"6+ hours coded",  code:"1f451", color:"#facc15", bonus:{ACHIEVEMENT_HOUR_BONUS[6]} }}, // crown
  {{ min:5, name:"Deep Work",       desc:"5+ hours coded",  code:"26a1",  color:"#f97316", bonus:{ACHIEVEMENT_HOUR_BONUS[5]} }}, // lightning
  {{ min:3, name:"Strong Session",  desc:"3+ hours coded",  code:"1f4aa", color:"#3b82f6", bonus:{ACHIEVEMENT_HOUR_BONUS[3]} }}, // flexed biceps
  {{ min:1, name:"Something Counts",desc:"1+ hour coded",   code:"1f331", color:"#22c55e", bonus:{ACHIEVEMENT_HOUR_BONUS[1]} }}, // seedling
];
const STREAK_TIERS = [
  {{ min:30, name:"Month Streak", desc:"30 days in a row", code:"1f3c6", color:"#a78bfa", bonus:{ACHIEVEMENT_STREAK_BONUS[30]} }}, // trophy
  {{ min:14, name:"Two Weeks",    desc:"14 days in a row", code:"1f30a", color:"#38bdf8", bonus:{ACHIEVEMENT_STREAK_BONUS[14]} }}, // wave
  {{ min:7,  name:"Week Streak",  desc:"7 days in a row",  code:"1f525", color:"#ef4444", bonus:{ACHIEVEMENT_STREAK_BONUS[7]} }},  // fire
  {{ min:3,  name:"Three Days",   desc:"3 days in a row",  code:"1f517", color:"#eab308", bonus:{ACHIEVEMENT_STREAK_BONUS[3]} }},  // link
];
const XP_MILESTONES = [
  {{ at:10000, name:"10K XP Legend", code:"1f451", color:"#ffd700", bonus:{ACHIEVEMENT_MILESTONE_BONUS[10000]} }},
  {{ at:5000,  name:"5K XP Master",  code:"1f3c6", color:"#c5c0f0", bonus:{ACHIEVEMENT_MILESTONE_BONUS[5000]} }},
  {{ at:1000,  name:"1K XP Veteran", code:"1f48e", color:"#a78bfa", bonus:{ACHIEVEMENT_MILESTONE_BONUS[1000]} }},
];

function hourTierFor(hrs)  {{ return HOUR_TIERS.find(t => hrs >= t.min)   || null; }}
function streakTierFor(s)  {{ return STREAK_TIERS.find(t => s   >= t.min) || null; }}

const todayHourTier   = hourTierFor(h);
const todayStreakTier = streakTierFor(streak);
const milestoneHit    = XP_MILESTONES.find(m => totalXPBefore < m.at && totalXP >= m.at);

const items = [];
if (todayHourTier)   items.push(todayHourTier);
if (todayStreakTier) items.push(todayStreakTier);
if (milestoneHit)    items.push({{...milestoneHit, desc:`Crossed ${{milestoneHit.at.toLocaleString()}} total XP`}});

const itemsBonusTotal = items.reduce((s,it) => s + it.bonus, 0);

const todayDateObj = new Date(todayStr + "T00:00:00");
const weekAgoObj    = new Date(todayDateObj); weekAgoObj.setDate(weekAgoObj.getDate() - 6);
let weekBonusXP = 0;
for (const p of allPages) {{
  const pd = new Date(dstr(p.date) + "T00:00:00");
  if (pd < weekAgoObj || pd > todayDateObj) continue;
  const ht = hourTierFor(Number(p.coding_time)||0);
  const st = streakTierFor(Number(p.streak)||0);
  if (ht) weekBonusXP += ht.bonus;
  if (st) weekBonusXP += st.bonus;
}}

const dateTitle    = todayDateObj.toLocaleDateString("en-GB", {{ day:"numeric", month:"long" }});
const dateWeekday  = todayDateObj.toLocaleDateString("en-GB", {{ weekday:"long" }});
const unlockedWord = items.length === 1 ? "achievement unlocked" : "achievements unlocked";

function hexToRgb(hex) {{ const v=hex.replace("#",""); return [parseInt(v.slice(0,2),16),parseInt(v.slice(2,4),16),parseInt(v.slice(4,6),16)]; }}
function rgba(hex, a) {{ const [r,g,b]=hexToRgb(hex); return `rgba(${{r}},${{g}},${{b}},${{a}})`; }}

function itemRow(it) {{
  const glow = rgba(it.color, 0.5);
  const bonusTag = `<div class="xpill" style="background:${{rgba(it.color,0.16)}};border:1px solid ${{rgba(it.color,0.45)}};color:${{it.color}}">+${{it.bonus}} XP</div>`;
  return `
  <div style="position:relative;display:flex;align-items:center;gap:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:18px;padding:14px 18px 14px 0;overflow:hidden">
    <div style="align-self:stretch;width:3px;border-radius:0 3px 3px 0;background:${{it.color}};box-shadow:0 0 12px ${{glow}}"></div>
    <div style="flex-shrink:0;width:44px;height:44px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09);box-shadow:0 0 18px ${{rgba(it.color,0.18)}}">
      ${{emoji(it.code)}}
    </div>
    <div style="flex:1;min-width:0">
      <div style="font-size:15.5px;font-weight:700;color:#f2f4f8;letter-spacing:-0.1px">${{it.name}}</div>
      <div style="font-size:12.5px;color:rgba(148,163,184,0.6);margin-top:2px">${{it.desc}}</div>
    </div>
    ${{bonusTag}}
  </div>`;
}}

let html = `
<style>.xpill{{flex-shrink:0;font-size:11.5px;font-weight:800;letter-spacing:0.4px;padding:7px 13px;border-radius:999px;white-space:nowrap}}</style>
<div style="
  position:relative;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:linear-gradient(165deg,#12141c 0%,#090a10 100%);
  border:1px solid rgba(255,255,255,0.08);
  border-radius:24px;
  padding:24px 24px 22px;
  margin:10px 0;
  overflow:hidden;
  box-shadow:0 24px 60px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05);
">
  <div style="position:absolute;top:-110px;left:-50px;width:300px;height:260px;background:radial-gradient(circle, rgba(59,130,246,0.32) 0%, transparent 70%);filter:blur(55px);pointer-events:none"></div>
  <div style="position:absolute;bottom:-130px;right:-70px;width:280px;height:250px;background:radial-gradient(circle, rgba(167,139,250,0.24) 0%, transparent 70%);filter:blur(55px);pointer-events:none"></div>
  <div style="position:absolute;inset:0;pointer-events:none;opacity:0.85">
    <div style="position:absolute;top:14px;right:190px;width:3px;height:3px;border-radius:50%;background:#fff;box-shadow:0 0 5px 1.5px rgba(255,255,255,0.65)"></div>
    <div style="position:absolute;top:38px;right:225px;width:2px;height:2px;border-radius:50%;background:#fff;box-shadow:0 0 4px 1px rgba(255,255,255,0.55)"></div>
    <div style="position:absolute;top:6px;right:155px;width:2px;height:2px;border-radius:50%;background:#fff;box-shadow:0 0 4px 1px rgba(255,255,255,0.55)"></div>
    <div style="position:absolute;top:50px;right:135px;width:3px;height:3px;border-radius:50%;background:#fff;box-shadow:0 0 5px 1.5px rgba(255,255,255,0.65)"></div>
    <div style="position:absolute;top:26px;right:100px;width:2px;height:2px;border-radius:50%;background:#fff;box-shadow:0 0 4px 1px rgba(255,255,255,0.55)"></div>
    <div style="position:absolute;top:66px;right:75px;width:2px;height:2px;border-radius:50%;background:#fff;box-shadow:0 0 4px 1px rgba(255,255,255,0.55)"></div>
  </div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:22px">
    <div>
      <div style="font-size:11px;letter-spacing:2.2px;color:rgba(148,163,184,0.6);font-weight:700;margin-bottom:7px">TODAY'S ACHIEVEMENTS</div>
      <div style="font-size:24px;font-weight:800;color:#f5f7fb;letter-spacing:-0.4px">${{dateTitle}}</div>
      <div style="font-size:12.5px;color:rgba(148,163,184,0.55);margin-top:4px">${{dateWeekday}} · ${{items.length}} unlocked today</div>
    </div>
    <div style="background:rgba(59,130,246,0.12);border:1px solid rgba(96,165,250,0.35);border-radius:999px;padding:7px 15px;font-size:12px;font-weight:700;color:#93c5fd;letter-spacing:0.3px;box-shadow:0 0 18px rgba(59,130,246,0.22);white-space:nowrap">+${{todayXP}} XP TODAY</div>
  </div>

  <div style="position:relative;display:flex;align-items:baseline;gap:12px;margin-bottom:20px;flex-wrap:wrap">
    <span style="font-size:46px;font-weight:800;letter-spacing:-2px;line-height:1;background:linear-gradient(180deg,#ffffff 0%,#9fb3d9 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">${{items.length}}</span>
    <span style="font-size:14px;color:rgba(203,213,225,0.55);font-weight:600">${{unlockedWord}}${{itemsBonusTotal > 0 ? ` · +${{itemsBonusTotal}} bonus XP` : ""}}</span>
    ${{weekBonusXP > 0
      ? `<span style="margin-left:auto;background:rgba(74,222,128,0.12);border:1px solid rgba(74,222,128,0.3);color:#86efac;font-size:12.5px;font-weight:700;padding:6px 12px;border-radius:999px">+${{weekBonusXP}} bonus XP this week</span>`
      : `<span style="margin-left:auto;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);color:rgba(203,213,225,0.55);font-size:12.5px;font-weight:600;padding:6px 12px;border-radius:999px">Keep coding →</span>`
    }}
  </div>

  <div style="position:relative;height:1px;background:rgba(255,255,255,0.08);margin-bottom:18px"></div>`;

if (items.length === 0) {{
  html += `
  <div style="position:relative;display:flex;align-items:center;gap:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);border-radius:18px;padding:20px 20px">
    <div style="flex-shrink:0;width:44px;height:44px;border-radius:13px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.09)">${{emoji("1f319")}}</div>
    <div>
      <div style="font-size:14.5px;font-weight:700;color:#e2e8f0">No achievements yet today</div>
      <div style="font-size:12.5px;color:rgba(148,163,184,0.55);margin-top:2px">Code a bit more to unlock one</div>
    </div>
  </div>`;
}} else {{
  html += `<div style="position:relative;display:flex;flex-direction:column;gap:10px">`;
  for (const it of items) html += itemRow(it);
  html += `</div>`;
}}

html += `
  <div style="position:relative;display:flex;justify-content:space-between;align-items:center;margin-top:18px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.07);font-size:11px;color:rgba(148,163,184,0.45);letter-spacing:0.3px">
    <div style="display:flex;gap:6px">
      ${{items.map(it => `<div style="width:6px;height:6px;border-radius:50%;background:${{it.color}}"></div>`).join("")}}
    </div>
    <span>Coding Progression System</span>
  </div>
</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## Skill Tree

```dataviewjs
const allPages = dv.pages('"daily"').where(p => p.top_lang != null).array();
const langTotals = {{}};
for (const p of allPages) {{
  const lang = String(p.top_lang || "Other");
  langTotals[lang] = (langTotals[lang] || 0) + (Number(p.top_lang_hours) || 0);
}}

const sorted = Object.entries(langTotals).sort((a,b) => b[1]-a[1]).slice(0,3);

const XP_PER_H  = {XP_PER_HOUR};
const BONUS     = {TOP_LANG_BONUS};

// Faceit-style кривая уровней
const LEVEL_FLOORS = [0, 200, 600, 1400, 3000, 5500, 9000, 12000, 15000, 20000];

function getLevelInfo(xp) {{
  let lvl = 1;
  for (let i = 0; i < LEVEL_FLOORS.length; i++) {{
    if (xp >= LEVEL_FLOORS[i]) lvl = i + 1;
  }}
  const floor = LEVEL_FLOORS[lvl - 1];
  const ceil  = lvl < 10 ? LEVEL_FLOORS[lvl] : null;
  const progress = ceil ? Math.min((xp - floor) / (ceil - floor), 1) : 1;
  const xpToNext = ceil ? Math.max(ceil - xp, 0) : 0;
  return {{ lvl, progress, xpToNext }};
}}

function hexToRgb(hex) {{
  const v = hex.replace("#","");
  return [parseInt(v.slice(0,2),16), parseInt(v.slice(2,4),16), parseInt(v.slice(4,6),16)];
}}
function rgba(hex, alpha) {{
  const [r,g,b] = hexToRgb(hex);
  return `rgba(${{r}},${{g}},${{b}},${{alpha}})`;
}}


function getLevelStyle(lvl) {{
  const fillMap = {{1:4, 2:14, 3:24, 4:44, 5:55, 6:65, 7:75, 8:86, 9:93, 10:100}};
  let color;
  if (lvl <= 1)      color = "#f1f5f9";
  else if (lvl <= 3) color = "#2ecc71";
  else if (lvl <= 7) color = "#f5c518";
  else if (lvl <= 9) color = "#ff8a1e";
  else                color = "#ef4444";
  return {{ color, fillPct: fillMap[lvl] }};
}}

function ringSVG(lvl, idx) {{
  const {{ color, fillPct }} = getLevelStyle(lvl);
  const r = 33, sw = 8, pad = 22;
  const size = (r + sw/2) * 2 + pad * 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const dash = (fillPct/100) * circ;
  const filterId = `ringGlow${{idx}}`;
  return `
  <svg width="${{size}}" height="${{size}}" viewBox="0 0 ${{size}} ${{size}}" style="overflow:visible;display:block">
    <defs>
      <filter id="${{filterId}}" x="-80%" y="-80%" width="260%" height="260%">
        <feGaussianBlur stdDeviation="4.5" result="blur"/>
        <feMerge>
          <feMergeNode in="blur"/>
          <feMergeNode in="SourceGraphic"/>
        </feMerge>
      </filter>
    </defs>
    <circle cx="${{c}}" cy="${{c}}" r="${{r}}" fill="#0c0c0e" stroke="rgba(255,255,255,0.08)" stroke-width="${{sw}}"/>
    <circle cx="${{c}}" cy="${{c}}" r="${{r}}" fill="none" stroke="${{color}}" stroke-width="${{sw}}"
      stroke-dasharray="${{dash}} ${{circ}}" stroke-linecap="round"
      transform="rotate(-90 ${{c}} ${{c}})" filter="url(#${{filterId}})"/>
    <text x="${{c}}" y="${{c+8}}" text-anchor="middle" font-size="25" font-weight="800" fill="${{color}}" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">${{lvl}}</text>
  </svg>`;
}}

const RANK_LABELS = ["TOP LANGUAGE", "RUNNER-UP", "THIRD PLACE"];

function skillCard(lang, hours, xp, idx) {{
  const {{ lvl, progress, xpToNext }} = getLevelInfo(xp);
  const {{ color }} = getLevelStyle(lvl);
  const glowSoft   = rgba(color, 0.22);
  const glowStrong = rgba(color, 0.6);
  const pct = Math.round(progress * 100);
  const subLabel = lvl < 10 ? `${{xpToNext}} XP to Level ${{lvl+1}}` : "Max level reached";
  const ring = ringSVG(lvl, idx);

  return `
  <div style="
    position:relative;
    background:linear-gradient(165deg,#141417 0%,#09090b 100%);
    border:1px solid rgba(255,255,255,0.07);
    border-radius:28px;
    padding:26px 26px 24px;
    margin-bottom:${{idx < 2 ? "16px" : "0"}};
    overflow:hidden;
    box-shadow:0 24px 50px rgba(0,0,0,0.5), 0 0 60px ${{glowSoft}};
  ">
    <div style="position:absolute;top:-50px;left:50%;transform:translateX(-50%);width:220px;height:120px;background:radial-gradient(ellipse, ${{glowSoft}} 0%, transparent 70%);pointer-events:none"></div>

    <div style="
      position:absolute;top:18px;right:18px;width:32px;height:32px;border-radius:50%;
      background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.16);
      display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:800;color:#ffffff;
    ">${{idx+1}}</div>

    <div style="position:relative;display:flex;align-items:center;gap:10px;margin-bottom:22px">
      <div style="flex-shrink:0">${{ring}}</div>
      <div style="min-width:0">
        <div style="font-size:11px;letter-spacing:1.3px;color:#a3a3b3;font-weight:800;margin-bottom:5px">${{RANK_LABELS[idx]}}</div>
        <div style="font-size:24px;font-weight:800;color:#ffffff;letter-spacing:-0.3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${{lang}}</div>
        <div style="font-size:13.5px;color:#9d9dab;margin-top:3px">${{hours.toFixed(1)}}h coded · ${{xp.toLocaleString()}} XP</div>
      </div>
    </div>

    <div style="
      position:relative;
      background:rgba(255,255,255,0.04);
      border:1px solid rgba(255,255,255,0.07);
      border-radius:18px;
      padding:16px 18px 18px;
    ">
      <div style="display:flex;align-items:center;margin-bottom:13px">
        <div style="width:8px;height:8px;margin-right:10px;border-radius:50%;background:${{color}};box-shadow:0 0 10px ${{glowStrong}};flex-shrink:0"></div>
        <span style="font-size:14px;color:#e4e4ec">${{subLabel}}</span>
        <span style="margin-left:auto;font-size:13px;font-weight:800;color:${{color}}">${{pct}}%</span>
      </div>
      <div style="position:relative;height:9px;border-radius:999px;background:rgba(255,255,255,0.08)">
        <div style="
          position:absolute;top:0;left:0;height:100%;
          width:${{Math.max(pct,3)}}%;border-radius:999px;
          background:${{color}};
          box-shadow:0 0 16px ${{glowStrong}}, 0 0 34px ${{glowSoft}};
        "></div>
      </div>
    </div>
  </div>`;
}}

let html = `
<div style="
  position:relative;
  background:#08080a;
  border:1px solid rgba(255,255,255,0.07);
  border-radius:28px;
  padding:28px;
  margin:10px 0;
  overflow:hidden;
  box-shadow:0 0 90px rgba(255,255,255,0.05), 0 30px 70px rgba(0,0,0,0.6);
">
  <div style="
    position:absolute;inset:0;pointer-events:none;opacity:0.55;
    background-image:
      linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px);
    background-size:120px 120px;
  "></div>
  <div style="
    position:absolute;left:-10%;right:-10%;top:32%;height:130px;
    background:linear-gradient(180deg, transparent, rgba(255,255,255,0.06), transparent);
    filter:blur(8px);pointer-events:none;
  "></div>
  <div style="
    position:absolute;left:-10%;right:-10%;top:66%;height:110px;
    background:linear-gradient(180deg, transparent, rgba(255,255,255,0.04), transparent);
    filter:blur(8px);pointer-events:none;
  "></div>
  <div style="
    position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
    width:85%;height:70%;
    background:radial-gradient(ellipse, rgba(255,255,255,0.10) 0%, transparent 65%);
    filter:blur(50px);pointer-events:none;
  "></div>

  <div style="position:relative">
    <div style="font-size:23px;font-weight:800;color:#ffffff;margin-bottom:5px;letter-spacing:-0.3px;">Skill Tree</div>
    <div style="font-size:13px;color:rgba(255,255,255,0.6);margin-bottom:20px;">Top 3 languages, all-time progress</div>`;

if (sorted.length === 0) {{
  html += `<div style="color:rgba(255,255,255,0.5);font-size:14px;">No data yet — start coding!</div>`;
}} else {{
  sorted.forEach(([lang, hours], idx) => {{
    const langXP = Math.round(hours * XP_PER_H * (idx === 0 ? BONUS : 1.0));
    html += skillCard(lang, hours, langXP, idx);
  }});
}}

html += `
    <div style="margin-top:16px;padding-top:12px;border-top:1px solid rgba(255,255,255,0.08);font-size:11.5px;color:rgba(255,255,255,0.45);display:flex;justify-content:space-between;">
      <span>Top language bonus: ×${{BONUS}}</span>
      <span>Coding Progression System</span>
    </div>
  </div>
</div>`;

const container = dv.el("div","");
container.innerHTML = html;

```

---

## Trophy Room

```dataviewjs
const allPages = dv.pages('"daily"').where(p => p.coding_time != null).array();
const totalH    = allPages.reduce((s,p) => s+(Number(p.coding_time)||0), 0);
const totalXP   = allPages.reduce((s,p) => s+(Number(p.xp)||0), 0);
const totalDays = allPages.length;
const maxDay    = Math.max(...allPages.map(p => Number(p.coding_time)||0), 0);
const maxDayXP  = Math.max(...allPages.map(p => Number(p.xp)||0), 0);
const daysOver5 = allPages.filter(p => (Number(p.coding_time)||0) >= 5).length;
const daysOver3 = allPages.filter(p => (Number(p.coding_time)||0) >= 3).length;

const langTotals = {{}};
for (const p of allPages) {{
  const lang = String(p.top_lang || "Other");
  langTotals[lang] = (langTotals[lang] || 0) + (Number(p.top_lang_hours) || 0);
}}
const histTopLang = Object.keys(langTotals).length
  ? Object.keys(langTotals).reduce((a,b) => langTotals[a]>langTotals[b]?a:b)
  : "Other";
const histTopH = langTotals[histTopLang] || 0;

const sorted = allPages.slice().sort((a,b) => String(a.date).localeCompare(String(b.date)));
let bestStreak = 0, cur = 0, prevDate = null;
for (const p of sorted) {{
  const d = new Date(String(p.date).slice(0,10));
  const h = Number(p.coding_time)||0;
  if (prevDate && (d-prevDate)/86400000===1 && h>={MIN_HOURS_FOR_STREAK}) cur++;
  else if (h>={MIN_HOURS_FOR_STREAK}) cur=1; else cur=0;
  bestStreak = Math.max(bestStreak, cur);
  prevDate = d;
}}

function roundPoly(points, r) {{
  const n = points.length;
  const cuts = [];
  for (let i = 0; i < n; i++) {{
    const pPrev = points[(i - 1 + n) % n];
    const p = points[i];
    const pNext = points[(i + 1) % n];
    const d1 = Math.hypot(pPrev[0]-p[0], pPrev[1]-p[1]) || 1e-6;
    const d2 = Math.hypot(pNext[0]-p[0], pNext[1]-p[1]) || 1e-6;
    const rr = Math.min(r, d1*0.45, d2*0.45);
    const inPt  = [p[0] + (pPrev[0]-p[0])/d1*rr, p[1] + (pPrev[1]-p[1])/d1*rr];
    const outPt = [p[0] + (pNext[0]-p[0])/d2*rr, p[1] + (pNext[1]-p[1])/d2*rr];
    cuts.push([inPt, p, outPt]);
  }}
  let d = `M ${{cuts[0][2][0].toFixed(2)}} ${{cuts[0][2][1].toFixed(2)}} `;
  for (let i = 1; i <= n; i++) {{
    const [inPt, vertex, outPt] = cuts[i % n];
    d += `L ${{inPt[0].toFixed(2)}} ${{inPt[1].toFixed(2)}} Q ${{vertex[0].toFixed(2)}} ${{vertex[1].toFixed(2)}} ${{outPt[0].toFixed(2)}} ${{outPt[1].toFixed(2)}} `;
  }}
  return d + "Z";
}}

const crownD      = roundPoly([[4,18],[6,8],[10,13],[12,6],[14,13],[18,8],[20,18]], 1.5);
const gemD        = roundPoly([[12,3],[19,9],[12,21],[5,9]], 1.7);
const shieldD     = roundPoly([[12,2.2],[19,5.8],[19,12],[12,21.6],[5,12],[5,5.8]], 1.5);
const rocketBodyD = roundPoly([[12,2],[16.5,10],[16.5,16],[7.5,16],[7.5,10]], 1.1);
const finLD       = roundPoly([[7.5,13],[3.2,17.6],[7.5,16.4]], 0.6);
const finRD       = roundPoly([[16.5,13],[20.8,17.6],[16.5,16.4]], 0.6);
const starburstD  = roundPoly([[12,2],[14,9],[21,9],[15.4,13.4],[17.4,21],[12,16.4],[6.6,21],[8.6,13.4],[3,9],[10,9]], 0.7);
const boltSmD     = roundPoly([[13,4],[7,13],[11,13],[10,20],[17,9],[13,9]], 0.55);
const boltMdD     = roundPoly([[14,2],[5,14],[10,14],[8.5,22],[18,9],[13,9]], 0.55);
const swordBladeD = roundPoly([[14.5,6.5],[18,10],[15.5,12.5],[12,9]], 0.5);
const chevBarD    = roundPoly([[12,2.6],[21.4,12.8],[21.4,16.6],[12,9.4],[2.6,16.6],[2.6,12.8]], 1.9);
const tailLD       = roundPoly([[9.4,13.6],[6,20.6],[8.6,19.2],[10.8,14.6]], 0.7);
const tailRD       = roundPoly([[14.6,13.6],[18,20.6],[15.4,19.2],[13.2,14.6]], 0.7);

const GLOW_ICONS = new Set(["flame1","flame2","flame3","spark","rocket","boltSm","boltMd","meteor","starburst"]);

const ICON_HOTSPOT = {{
  cup: [8.5,6], flame1:[10,8], flame2:[10,7], flame3:[10,6], crown:[7,10],
  shield:[8,7], diamond:[8.5,8], rocket:[9,7], medal:[9,7.5], spark:[9,7],
  clock:[9,8], hourglass:[9,6], terminal:[7,9], gear:[9,4], chip:[9,9],
  coin:[9,8], coinsStack:[9,7], moon:[8.5,8.5], globe:[8.5,8], seal:[9,7],
  hrBadge5:[7,8], hrBadge10:[5.5,7], hrBadge25:[5.5,7], trophyCup:[8.5,6],
}};

const ICON_BLUR = {{
  hrBadge5: 0.35, hrBadge10: 0.35, hrBadge25: 0.35,
  terminal: 0.9, chip: 1.0, gear: 1.0, chain: 1.0, swordsCross: 1.0,
}};

const ICONS = {{
  flag:        c => `<line x1="6" y1="3" x2="6" y2="21" stroke="${{c}}" stroke-width="2.2" stroke-linecap="round"/><path d="M6 4h12l-3.5 4.5L18 13H6" fill="${{c}}"/>`,
  hrBadge5:    c => `<text x="12" y="16.6" text-anchor="middle" font-family="-apple-system,'SF Pro Display','Segoe UI',sans-serif" font-size="14" font-weight="800" fill="${{c}}">5</text><rect x="8" y="18.6" width="8" height="1.8" rx="0.9" fill="${{c}}" opacity="0.6"/>`,
  hrBadge10:   c => `<circle cx="12" cy="12" r="9" fill="none" stroke="${{c}}" stroke-width="1.7" opacity="0.55"/><text x="12" y="16" text-anchor="middle" font-family="-apple-system,'SF Pro Display','Segoe UI',sans-serif" font-size="10" font-weight="800" fill="${{c}}">10</text>`,
  hrBadge25:   c => `<text x="12" y="15.4" text-anchor="middle" font-family="-apple-system,'SF Pro Display','Segoe UI',sans-serif" font-size="9.5" font-weight="800" fill="${{c}}">25</text><path d="M6 19 L12 16.3 L18 19" fill="none" stroke="${{c}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity="0.65"/>`,
  hourglass:   c => `<path d="M6.5 3 H17.5 A1.4 1.4 0 0 1 17.5 5.8 H6.5 A1.4 1.4 0 0 1 6.5 3 Z" fill="${{c}}"/><path d="M6.5 18.2 H17.5 A1.4 1.4 0 0 1 17.5 21 H6.5 A1.4 1.4 0 0 1 6.5 18.2 Z" fill="${{c}}"/><path d="M7.2 5 L16.8 5 L12.9 11.3 C12.5 12 11.5 12 11.1 11.3 Z" fill="${{c}}" opacity="0.85"/><path d="M7.2 19 L16.8 19 L12.9 12.7 C12.5 12 11.5 12 11.1 12.7 Z" fill="${{c}}" opacity="0.6"/>`,
  clock:       c => `<circle cx="12" cy="12" r="9" fill="${{c}}"/><line x1="12" y1="12" x2="12" y2="6.6" stroke="#0a0a0a" stroke-width="1.8" stroke-linecap="round" opacity="0.5"/><line x1="12" y1="12" x2="15.6" y2="13.8" stroke="#0a0a0a" stroke-width="1.8" stroke-linecap="round" opacity="0.5"/><circle cx="12" cy="12" r="1.3" fill="#0a0a0a" opacity="0.5"/>`,
  medal:       c => `<circle cx="12" cy="9" r="6.5" fill="${{c}}"/><path d="M12 5.6 L12.9 7.7 L15.1 8 L13.5 9.5 L13.9 11.7 L12 10.6 L10.1 11.7 L10.5 9.5 L8.9 8 L11.1 7.7 Z" fill="#0a0a0a" opacity="0.28"/><path d="${{tailLD}}" fill="${{c}}" opacity="0.85"/><path d="${{tailRD}}" fill="${{c}}" opacity="0.85"/>`,
  shield:      c => `<path d="${{shieldD}}" fill="${{c}}"/><path d="M8.4 12 L11 14.6 L16 9.1" fill="none" stroke="${{c.indexOf('url')===0 ? '#ffffff' : 'none'}}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>`,
  runner:      c => `<ellipse cx="7.6" cy="15" rx="3.3" ry="5" fill="${{c}}" transform="rotate(-18 7.6 15)"/><circle cx="8.7" cy="9" r="2" fill="${{c}}" opacity="0.9"/><ellipse cx="16.4" cy="9" rx="3.3" ry="5" fill="${{c}}" opacity="0.88" transform="rotate(18 16.4 9)"/><circle cx="15.3" cy="14.6" r="2" fill="${{c}}" opacity="0.7"/>`,
  mountain:    c => `<path d="M2.5 19.5 L9 7.5 L13 13.8 L16 9.5 L21.5 19.5 Z" fill="${{c}}"/><path d="M9 7.5 L11.2 11 L8 11.5 Z" fill="#0a0a0a" opacity="0.18"/>`,
  diamond:     c => `<path d="${{gemD}}" fill="${{c}}"/><path d="M7 8.3 Q12 6.6 17 8.3" fill="none" stroke="${{c.indexOf('url')===0 ? '#ffffff' : 'none'}}" stroke-width="1.3" stroke-linecap="round" opacity="0.55"/>`,
  crown:       c => `<path d="${{crownD}}" fill="${{c}}" opacity="0.94"/><line x1="4" y1="19" x2="20" y2="19" stroke="${{c}}" stroke-width="1.8" stroke-linecap="round"/><circle cx="6" cy="8" r="1" fill="${{c.indexOf('url')===0 ? '#ffffff' : c}}" opacity="0.8"/><circle cx="12" cy="6" r="1.1" fill="${{c.indexOf('url')===0 ? '#ffffff' : c}}" opacity="0.85"/><circle cx="18" cy="8" r="1" fill="${{c.indexOf('url')===0 ? '#ffffff' : c}}" opacity="0.8"/>`,
  codeBrackets:c => `<path d="M9 5.5 L3.5 12 L9 18.5" stroke="${{c}}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M15 5.5 L20.5 12 L15 18.5" stroke="${{c}}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`,
  terminal:    c => `<path d="M5.5 6.5 L12.5 12 L5.5 17.5" fill="none" stroke="${{c}}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="13.5" y="15.4" width="6.5" height="3.2" rx="1.6" fill="${{c}}"/>`,
  gear:        c => `<circle cx="12" cy="12" r="4.6" fill="${{c}}"/><rect x="10.4" y="1.4" width="3.2" height="6.8" rx="1.5" fill="${{c}}"/><rect x="10.4" y="15.8" width="3.2" height="6.8" rx="1.5" fill="${{c}}"/><rect x="1.4" y="10.4" width="6.8" height="3.2" rx="1.5" fill="${{c}}"/><rect x="15.8" y="10.4" width="6.8" height="3.2" rx="1.5" fill="${{c}}"/><rect x="4.6" y="4.6" width="4.4" height="4.4" rx="1.2" fill="${{c}}" transform="rotate(45 6.8 6.8)"/><rect x="15" y="4.6" width="4.4" height="4.4" rx="1.2" fill="${{c}}" transform="rotate(45 17.2 6.8)"/><rect x="4.6" y="15" width="4.4" height="4.4" rx="1.2" fill="${{c}}" transform="rotate(45 6.8 17.2)"/><rect x="15" y="15" width="4.4" height="4.4" rx="1.2" fill="${{c}}" transform="rotate(45 17.2 17.2)"/>`,
  chip:        c => `<rect x="7" y="7" width="10" height="10" rx="2.5" fill="${{c}}"/><path d="M9 3v4M12 3v4M15 3v4M9 17v4M12 17v4M15 17v4M3 9h4M3 12h4M3 15h4M17 9h4M17 12h4M17 15h4" stroke="${{c}}" stroke-width="2.2" stroke-linecap="round"/>`,
  infinity:    c => `<circle cx="9" cy="12" r="4.2" fill="none" stroke="${{c}}" stroke-width="3.2"/><circle cx="15" cy="12" r="4.2" fill="none" stroke="${{c}}" stroke-width="3.2"/>`,
  spark:       c => `<path d="M12 1.4 Q13.4 9.4 22 12 Q13.4 14.4 12 22.6 Q10.6 14.4 2 12 Q10.6 9.4 12 1.4 Z" fill="${{c}}"/>`,
  coin:        c => `<circle cx="12" cy="12" r="8.5" fill="${{c}}"/><circle cx="12" cy="12" r="8.5" fill="none" stroke="#0a0a0a" stroke-width="1" opacity="0.2"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="#0a0a0a" stroke-width="1" opacity="0.28"/>`,
  coinsStack:  c => `<ellipse cx="12" cy="17" rx="7" ry="2.8" fill="${{c}}" opacity="0.6"/><ellipse cx="12" cy="12.3" rx="7" ry="2.8" fill="${{c}}" opacity="0.8"/><ellipse cx="12" cy="7.6" rx="7" ry="2.8" fill="${{c}}"/>`,
  sword:       c => `<line x1="6" y1="19" x2="16" y2="9" stroke="${{c}}" stroke-width="2.6" stroke-linecap="round"/><path d="${{swordBladeD}}" fill="${{c}}"/><line x1="6" y1="19" x2="4.3" y2="20.7" stroke="${{c}}" stroke-width="2.6" stroke-linecap="round"/>`,
  swordsCross: c => `<line x1="5" y1="19" x2="19" y2="5" stroke="${{c}}" stroke-width="2.6" stroke-linecap="round"/><line x1="5" y1="5" x2="19" y2="19" stroke="${{c}}" stroke-width="2.6" stroke-linecap="round"/><circle cx="12" cy="12" r="2.6" fill="${{c}}"/>`,
  starburst:   c => `<path d="${{starburstD}}" fill="${{c}}" opacity="0.94"/>`,
  chain:       c => `<rect x="4" y="8" width="8" height="12" rx="4" fill="none" stroke="${{c}}" stroke-width="2.6" transform="rotate(-20 8 14)"/><rect x="12" y="4" width="8" height="12" rx="4" fill="none" stroke="${{c}}" stroke-width="2.6" transform="rotate(-20 16 10)"/>`,
  flame1:      c => `<path d="M12 5 C14.5 8 15.5 10 15.5 12.5 C15.5 14.8 14 16.3 12 16.3 C10 16.3 8.5 14.8 8.5 12.5 C8.5 11.2 8.9 10.2 9.7 10.8 C9.7 9 10.4 7 12 5 Z" fill="${{c}}"/>`,
  flame2:      c => `<path d="M12 3.8 C15 7.3 16.3 9.8 16.3 12.6 C16.3 15.4 14.4 17.2 12 17.2 C9.6 17.2 7.7 15.4 7.7 12.6 C7.7 11 8.2 9.8 9.2 10.6 C9.2 8.5 10.1 6 12 3.8 Z" fill="${{c}}"/>`,
  flame3:      c => `<path d="M12 2 C15.5 6.5 17 9.5 17 12.5 C17 16 14.5 18 12 18 C9.5 18 7 16 7 12.5 C7 10.5 7.7 9 9 10 C9 7.5 10 5 12 2 Z" fill="${{c}}"/>`,
  wave:        c => `<path d="M2 14 Q6 8 10 14 T18 14 T22 14" fill="none" stroke="${{c}}" stroke-width="3" stroke-linecap="round"/>`,
  calendarCk:  c => `<rect x="4" y="5" width="16" height="15" rx="3" fill="${{c}}"/><rect x="4" y="5" width="16" height="4.2" rx="3" fill="#0a0a0a" opacity="0.22"/><path d="M8 14l2.5 2.5L16 11" stroke="#0a0a0a" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity="0.55"/>`,
  trophyCup:   c => `<path d="M7 4h10v4a5 5 0 0 1-10 0z" fill="${{c}}"/><path d="M7 5H4.3a2.8 2.8 0 0 0 2.8 4.6" fill="none" stroke="${{c}}" stroke-width="1.8" stroke-linecap="round"/><path d="M17 5h2.7a2.8 2.8 0 0 1-2.8 4.6" fill="none" stroke="${{c}}" stroke-width="1.8" stroke-linecap="round"/><rect x="10.6" y="12.5" width="2.8" height="5" fill="${{c}}"/><rect x="7" y="18.6" width="10" height="2.4" rx="1.2" fill="${{c}}"/>`,
  moon:        c => `<circle cx="12" cy="12" r="8.5" fill="${{c}}" opacity="0.92"/><circle cx="8.5" cy="8.5" r="1.4" fill="#000" opacity="0.22"/><circle cx="15" cy="14" r="2" fill="#000" opacity="0.18"/><circle cx="10.5" cy="16" r="1.1" fill="#000" opacity="0.18"/>`,
  boltSm:      c => `<path d="${{boltSmD}}" fill="${{c}}"/>`,
  boltMd:      c => `<path d="${{boltMdD}}" fill="${{c}}"/>`,
  eyeFocus:    c => `<circle cx="12" cy="12" r="9" fill="none" stroke="${{c}}" stroke-width="2.6"/><circle cx="12" cy="12" r="5" fill="${{c}}" opacity="0.32"/><circle cx="12" cy="12" r="2.2" fill="${{c}}"/>`,
  rocket:      c => `<path d="${{rocketBodyD}}" fill="${{c}}" opacity="0.94"/><circle cx="12" cy="9.5" r="1.6" fill="#0a0a0a" opacity="0.55"/><circle cx="12" cy="9.5" r="1.6" fill="none" stroke="${{c.indexOf('url')===0 ? '#ffffff' : 'none'}}" stroke-width="0.7" opacity="0.6"/><path d="${{finLD}}" fill="${{c}}" opacity="0.75"/><path d="${{finRD}}" fill="${{c}}" opacity="0.75"/><path d="M9.7 16 L9 20.5 L12 18.5 L15 20.5 L14.3 16 Z" fill="${{c}}" opacity="0.55"/>`,
  meteor:      c => `<circle cx="15" cy="9" r="3.4" fill="${{c}}"/><path d="M12 12 L4 20M9 13 L3 17M13 15 L8 21" stroke="${{c}}" stroke-width="2.2" stroke-linecap="round" opacity="0.65"/>`,
  grid:        c => `<rect x="4" y="4" width="7" height="7" rx="2" fill="${{c}}" opacity="0.9"/><rect x="13" y="4" width="7" height="7" rx="2" fill="${{c}}" opacity="0.75"/><rect x="4" y="13" width="7" height="7" rx="2" fill="${{c}}" opacity="0.75"/><rect x="13" y="13" width="7" height="7" rx="2" fill="${{c}}" opacity="0.6"/>`,
  blocks:      c => `<rect x="4" y="14" width="6" height="6" rx="1.4" fill="${{c}}" opacity="0.55"/><rect x="10" y="14" width="6" height="6" rx="1.4" fill="${{c}}" opacity="0.75"/><rect x="7" y="8" width="6" height="6" rx="1.4" fill="${{c}}"/><rect x="14" y="8" width="6" height="6" rx="1.4" fill="${{c}}" opacity="0.88"/>`,
  dot1:        c => `<circle cx="12" cy="12" r="4.6" fill="${{c}}"/>`,
  dots7:       c => `<circle cx="3.2" cy="12" r="2.1" fill="${{c}}"/><circle cx="7.4" cy="12" r="2.1" fill="${{c}}"/><circle cx="11.6" cy="12" r="2.1" fill="${{c}}"/><circle cx="15.8" cy="12" r="2.1" fill="${{c}}"/><circle cx="20" cy="12" r="2.1" fill="${{c}}" opacity="0.55"/>`,
  calendarPg:  c => `<rect x="4" y="5" width="16" height="15" rx="3" fill="${{c}}"/><rect x="4" y="5" width="16" height="4.2" rx="3" fill="#0a0a0a" opacity="0.22"/><line x1="8" y1="2.4" x2="8" y2="6.6" stroke="${{c}}" stroke-width="2.2" stroke-linecap="round"/><line x1="16" y1="2.4" x2="16" y2="6.6" stroke="${{c}}" stroke-width="2.2" stroke-linecap="round"/>`,
  calendarSt:  c => `<rect x="6.5" y="7" width="13.5" height="11.5" rx="3" fill="${{c}}" opacity="0.45"/><rect x="4" y="5" width="13.5" height="11.5" rx="3" fill="${{c}}"/><rect x="4" y="5" width="13.5" height="3.6" rx="3" fill="#0a0a0a" opacity="0.2"/>`,
  seal:        c => `<circle cx="12" cy="10" r="7" fill="${{c}}"/><path d="M8 16 L6 21 L12 18 L18 21 L16 16" fill="${{c}}" opacity="0.85"/><path d="M9 10l2 2 4-4" stroke="#0a0a0a" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round" opacity="0.5"/>`,
  globe:       c => `<circle cx="12" cy="12" r="8.5" fill="${{c}}"/><ellipse cx="12" cy="12" rx="3.4" ry="8.5" fill="none" stroke="#0a0a0a" stroke-width="1.3" opacity="0.35"/><line x1="3.5" y1="12" x2="20.5" y2="12" stroke="#0a0a0a" stroke-width="1.3" opacity="0.35"/><path d="M5 7.5c3.2 1.6 10.8 1.6 14 0M5 16.5c3.2-1.6 10.8-1.6 14 0" stroke="#0a0a0a" stroke-width="1.1" fill="none" opacity="0.3"/>`,
}};

// [condition, name, description, category color, ключ иконки]
const trophies = [
  // Hours coded
  [totalH>=1,     "First Step",            "1h coded",              "#2ea043", "flag"],
  [totalH>=5,     "Recruit",               "5h coded",              "#2ea043", "hrBadge5"],
  [totalH>=10,    "10 Hours",              "10h coded",             "#2ea043", "hrBadge10"],
  [totalH>=25,    "25 Hours",              "25h coded",             "#40a0f0", "hrBadge25"],
  [totalH>=50,    "50 Hours",              "50h coded",             "#40a0f0", "hourglass"],
  [totalH>=75,    "75 Hours",              "75h coded",             "#40a0f0", "clock"],
  [totalH>=100,   "Centurion",             "100h coded",            "#f0c040", "medal"],
  [totalH>=200,   "200 Hours",             "200h coded",            "#f0c040", "shield"],
  [totalH>=500,   "Half Marathon",         "500h coded",            "#f07040", "runner"],
  [totalH>=750,   "750 Hours",             "750h coded",            "#f07040", "mountain"],
  [totalH>=1000,  "Millennium",            "1000h coded",           "#ffd700", "diamond"],
  [totalH>=2000,  "Elite",                 "2000h coded",           "#ffd700", "crown"],
  // ── Top language (dynamic) ──
  [histTopH>=1,   "First Hour",                "1h "+histTopLang,   "#2ea043", "codeBrackets"],
  [histTopH>=10,  "10 Hours "+histTopLang,     "10h "+histTopLang,  "#2ea043", "terminal"],
  [histTopH>=50,  "50 Hours "+histTopLang,     "50h "+histTopLang,  "#40a0f0", "gear"],
  [histTopH>=100, "100 Hours "+histTopLang,    "100h "+histTopLang, "#f0c040", "chip"],
  [histTopH>=500, "500 Hours "+histTopLang,    "500h "+histTopLang, "#ffd700", "infinity"],
  // ── XP ──
  [totalXP>=50,   "First Sparks",          "50 XP",                "#7F77DD", "spark"],
  [totalXP>=100,  "First Hundred",         "100 XP",               "#7F77DD", "coin"],
  [totalXP>=250,  "250 XP",                "Quarter thousand",     "#7F77DD", "diamond"],
  [totalXP>=500,  "500 XP",                "Half thousand",        "#a090ff", "coinsStack"],
  [totalXP>=1000, "Veteran",               "1000 XP",              "#a090ff", "medal"],
  [totalXP>=2500, "2500 XP",               "Elite Fighter",        "#c5c0f0", "sword"],
  [totalXP>=5000, "Master",                "5000 XP",              "#c5c0f0", "starburst"],
  [totalXP>=10000,"Legend",                "10000 XP",             "#ffd700", "crown"],
  // ── Streak ──
  [bestStreak>=2, "First Chain",           "2 days in a row",      "#f0c040", "chain"],
  [bestStreak>=3, "Three Days",            "3 days in a row",      "#f0c040", "flame1"],
  [bestStreak>=5, "Wave",                  "5 days in a row",      "#f0c040", "wave"],
  [bestStreak>=7, "Week Streak",           "7 days in a row",      "#f07040", "calendarCk"],
  [bestStreak>=14,"Two Weeks",             "14 days in a row",     "#f07040", "flame2"],
  [bestStreak>=21,"Three Weeks",           "21 days in a row",     "#ff6b35", "flame3"],
  [bestStreak>=30,"Month Streak",          "30 days in a row",     "#ffd700", "trophyCup"],
  [bestStreak>=60,"Two Months",            "60 days in a row",     "#ffd700", "moon"],
  [bestStreak>=100,"Century",              "100 days in a row",    "#ffd700", "starburst"],
  // ── Daily records ──
  [maxDay>=3,     "3h In A Day",           "daily record 3h",      "#40a0f0", "boltSm"],
  [maxDay>=5,     "5h In A Day",           "daily record 5h",      "#40a0f0", "boltMd"],
  [maxDay>=6,     "Deep Work",             "daily record 6h",      "#f07040", "eyeFocus"],
  [maxDay>=8,     "8h In A Day",           "daily record 8h",      "#ffd700", "rocket"],
  [maxDayXP>=80,  "Explosive Day",         "80+ XP in a day",      "#f07040", "spark"],
  [maxDayXP>=120, "Meteor",                "120+ XP in a day",     "#ffd700", "meteor"],
  // ── Consistency ──
  [daysOver3>=5,  "Systematic",            "5 days of 3h+",        "#40a0f0", "grid"],
  [daysOver3>=20, "Builder",               "20 days of 3h+",       "#f0c040", "blocks"],
  [daysOver5>=3,  "Code Warrior",          "3 days of 5h+",        "#f07040", "swordsCross"],
  [daysOver5>=10, "Iron Will",             "10 days of 5h+",       "#ffd700", "shield"],
  // ── Days in the system ──
  [totalDays>=1,  "Day One",               "1 day in the system",  "#8a8a94", "dot1"],
  [totalDays>=7,  "Week In",               "7 days",               "#8a8a94", "dots7"],
  [totalDays>=14, "Fortnight In",          "14 days",              "#9a9aa4", "calendarPg"],
  [totalDays>=30, "Month In",              "30 days",              "#9a9aa4", "calendarPg"],
  [totalDays>=60, "Two Months In",         "60 days",              "#a8a8b4", "calendarSt"],
  [totalDays>=100,"100 Days",              "100 days in the system","#c5b98a", "seal"],
  [totalDays>=365,"Year In",               "365 days",             "#ffd700", "globe"],
];

const withHue = trophies.map((t, i) => [...t, Math.round((i * 137.508) % 360)]);
const earned = withHue.filter(([c]) => c);
const locked = withHue.filter(([c]) => !c);
const pct = Math.round(earned.length / trophies.length * 100);

function progressColor(p) {{
  const stops = [
    {{ p: 0,   rgb: [250, 204, 130] }},  // мягкий жёлтый
    {{ p: 33,  rgb: [249, 149, 60]  }},  // оранжевый
    {{ p: 66,  rgb: [239, 84, 84]   }},  // красный
    {{ p: 100, rgb: [167, 139, 250] }},  // фиолетовый
  ];
  let lo = stops[0], hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {{
    if (p >= stops[i].p && p <= stops[i + 1].p) {{ lo = stops[i]; hi = stops[i + 1]; break; }}
  }}
  const span = (hi.p - lo.p) || 1;
  const t = (p - lo.p) / span;
  const r = Math.round(lo.rgb[0] + (hi.rgb[0] - lo.rgb[0]) * t);
  const g = Math.round(lo.rgb[1] + (hi.rgb[1] - lo.rgb[1]) * t);
  const b = Math.round(lo.rgb[2] + (hi.rgb[2] - lo.rgb[2]) * t);
  return [r, g, b];
}}
const [pr, pg, pb] = progressColor(pct);
const progRgb   = `${{pr}},${{pg}},${{pb}}`;
const progLight = `rgb(${{Math.min(pr+40,255)}},${{Math.min(pg+40,255)}},${{Math.min(pb+40,255)}})`;
const progDeep  = `rgb(${{Math.max(pr-50,0)}},${{Math.max(pg-50,0)}},${{Math.max(pb-50,0)}})`;

const EMOJI_MAP = {{
  flag: "1f6a9", hrBadge5: "0035-fe0f-20e3", hrBadge10: "1f51f", hrBadge25: "1f3af",
  hourglass: "231b", clock: "23f1-fe0f", medal: "1f3c5", shield: "1f6e1-fe0f",
  runner: "1f3c3", mountain: "26f0-fe0f", diamond: "1f48e", crown: "1f451",
  codeBrackets: "1f4bb", terminal: "2328-fe0f", gear: "2699-fe0f", chip: "1f9e0",
  infinity: "267e-fe0f", spark: "2728", coin: "1fa99", coinsStack: "1f4b0",
  sword: "2694-fe0f", starburst: "1f31f", chain: "1f517",
  flame1: "1f525", flame2: "1f525", flame3: "1f525",
  wave: "1f30a", calendarCk: "1f4c5", trophyCup: "1f3c6", moon: "1f319",
  boltSm: "1f4a5", boltMd: "26a1", eyeFocus: "1f441-fe0f", rocket: "1f680",
  meteor: "2604-fe0f", grid: "1f9f1", blocks: "1f3d7-fe0f", swordsCross: "1f5e1-fe0f",
  dot1: "1f331", dots7: "1f4c6", calendarPg: "1f5d3-fe0f", calendarSt: "1f4da",
  seal: "1f396-fe0f", globe: "1f310",
}};
function emojiUrl(code) {{
  return `https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-160/${{code}}.png`;
}}

function tile(name, desc, iconKey, hue, isLocked, idx) {{
  const emojiCode = EMOJI_MAP[iconKey] || "2b50";

  if (isLocked) {{
    return `
    <div style="
      background:linear-gradient(160deg,#101013,#08080a);
      border:1px solid rgba(255,255,255,0.04);
      border-radius:20px;
      padding:13px 10px 11px;
      text-align:center;
    ">
      <div style="display:flex;align-items:center;justify-content:center;height:34px;margin-bottom:8px">
        <img src="${{emojiUrl(emojiCode)}}" width="26" height="26" style="display:block;filter:grayscale(1) brightness(0.55);opacity:0.55" alt=""/>
      </div>
      <div style="font-size:10px;font-weight:600;color:#454550;line-height:1.25">${{name}}</div>
      <div style="font-size:8.5px;color:#2c2c33;margin-top:2px">${{desc}}</div>
    </div>`;
  }}

  const accent  = `hsl(${{hue}},78%,58%)`;
  const descClr = `hsla(${{hue}},20%,74%,0.55)`;

  return `
  <div style="
    background:
      linear-gradient(160deg, rgba(255,255,255,0.055) 0%, rgba(255,255,255,0.012) 55%, transparent 100%),
      #0a0a0d;
    border:1px solid rgba(255,255,255,0.08);
    border-radius:26px;
    padding:22px 16px 18px;
    position:relative;
    overflow:hidden;
    text-align:center;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.10),
      inset 0 -22px 30px rgba(0,0,0,0.4),
      0 0 26px hsla(${{hue}},70%,50%,0.10),
      0 16px 30px rgba(0,0,0,0.55);
  ">
    <div style="
      position:absolute;top:0;left:12%;right:12%;height:38%;
      background:linear-gradient(180deg, rgba(255,255,255,0.06), transparent);
      border-radius:0 0 50% 50% / 0 0 100% 100%;
      pointer-events:none;
    "></div>
    <div style="
      position:relative;display:flex;align-items:center;justify-content:center;
      height:128px;margin-bottom:14px;
    ">
      <div style="
        position:absolute;width:96px;height:96px;border-radius:50%;
        background:radial-gradient(circle, ${{accent}}55 0%, transparent 70%);
        filter:blur(14px);pointer-events:none;
      "></div>
      <img src="${{emojiUrl(emojiCode)}}" width="84" height="84" style="
        display:block;position:relative;
        filter:drop-shadow(0 10px 18px ${{accent}}66) drop-shadow(0 2px 5px rgba(0,0,0,0.55));
      " alt=""/>
    </div>
    <div style="position:relative;font-size:13px;font-weight:700;color:#f4f4f8;line-height:1.3">${{name}}</div>
    <div style="position:relative;font-size:10.5px;color:${{descClr}};margin-top:4px">${{desc}}</div>
  </div>`;
}}

let html = `
<div style="
  font-family:'SF Mono','Consolas',monospace;
  background:linear-gradient(160deg,#0e0e12 0%,#08080a 100%);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:20px;
  padding:22px 22px 22px;
  color:#e5e5e5;
  box-shadow:0 0 40px rgba(0,0,0,0.35);
  margin:8px 0;
">

<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
  <div>
    <div style="font-size:11px;color:#8b8b93;letter-spacing:2px;font-weight:600">TROPHY ROOM</div>
    <div style="font-size:13px;color:#5a5a64;margin-top:3px">${{pct}}% collection complete</div>
  </div>
  <div style="text-align:center;background:#151517;border:1px solid #232326;border-radius:12px;padding:8px 16px">
    <div style="font-size:20px;font-weight:800;color:rgb(${{progRgb}});line-height:1">${{earned.length}}<span style="font-size:12px;color:#6b6b73;font-weight:500">/${{trophies.length}}</span></div>
    <div style="font-size:9px;color:#6b6b73;letter-spacing:1px;margin-top:3px">EARNED</div>
  </div>
</div>

<div style="position:relative;height:34px;border-radius:999px;background:linear-gradient(180deg,#1a1a1e 0%,#0b0b0d 100%);border:1px solid rgba(255,255,255,0.06);box-shadow:inset 0 3px 8px rgba(0,0,0,0.55);margin-bottom:22px;overflow:visible">
  <div style="
    position:absolute;top:0;left:0;bottom:0;width:${{pct}}%;border-radius:999px;overflow:hidden;
    background:linear-gradient(90deg, ${{progLight}} 0%, rgb(${{progRgb}}) 55%, ${{progDeep}} 100%);
    box-shadow:0 0 20px rgba(${{progRgb}},0.6), 0 0 42px rgba(${{progRgb}},0.3), inset 0 1px 0 rgba(255,255,255,0.35);
  ">
    <div style="position:absolute;inset:0;background:repeating-linear-gradient(115deg, rgba(255,255,255,0.28) 0px, rgba(255,255,255,0.28) 2px, transparent 2px, transparent 11px);mix-blend-mode:overlay;opacity:0.5"></div>
  </div>
  <div style="position:absolute;top:50%;left:${{pct}}%;transform:translate(-50%,-50%);width:38px;height:38px;pointer-events:none">
    <div style="position:absolute;inset:-9px;border-radius:50%;background:radial-gradient(circle, rgba(${{progRgb}},0.55) 0%, transparent 70%);filter:blur(5px)"></div>
    <div style="position:relative;width:38px;height:38px;border-radius:50%;background:radial-gradient(circle at 35% 28%,#2a1608 0%,#0c0704 75%);border:2px solid rgba(${{progRgb}},0.85);box-shadow:0 0 14px rgba(${{progRgb}},0.7),0 3px 8px rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;overflow:hidden">
      <img src="${{emojiUrl("1f680")}}" width="27" height="27" style="display:block;transform:rotate(45deg);filter:drop-shadow(0 1px 2px rgba(0,0,0,0.5))" alt=""/>
    </div>
  </div>
</div>

<div style="font-size:10px;color:#7ee787;letter-spacing:1.5px;margin-bottom:10px">EARNED</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:${{locked.length>0?"24px":"0"}}">
${{earned.map(([,name,desc,,icon,hue], idx) => tile(name,desc,icon,hue,false,idx)).join("")}}
</div>`;

if (locked.length > 0) {{
  html += `
<div style="font-size:10px;color:#4a4a54;letter-spacing:1.5px;margin-bottom:10px">LOCKED</div>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px">
${{locked.map(([,name,desc,,icon,hue], idx) => tile(name,desc,icon,hue,true,idx)).join("")}}
</div>`;
}}

html += `</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## Leaderboard

```dataviewjs
const MIN_HOURS = {MIN_HOURS_FOR_STREAK};
const pages = dv.pages('"daily"').where(p => p.xp != null).array();

function toDateStr(val) {{
  if (!val) return null;
  if (typeof val === "string") return val.slice(0, 10);
  if (val.toFormat) return val.toFormat("yyyy-MM-dd");
  if (val instanceof Date) return localDateStr(val);
  return String(val).slice(0, 10);
}}

function localDateStr(d) {{
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${{y}}-${{m}}-${{day}}`;
}}

const byDate = {{}};
for (const p of pages) {{
  const dateStr = toDateStr(p.date) || p.file.name;
  if (dateStr) byDate[dateStr] = Number(p.coding_time) || 0;
}}

function calcCurrentStreak() {{
  let streak = 0;
  let d = new Date();
  while (true) {{
    const key = localDateStr(d);
    const h = byDate[key] || 0;
    if (h >= MIN_HOURS) {{ streak++; d.setDate(d.getDate() - 1); }} else {{ break; }}
  }}
  return streak;
}}

const youStreak = calcCurrentStreak();

const now         = new Date();
const todayDate   = new Date(now.getFullYear(), now.getMonth(), now.getDate()); // локальная полночь
const dowToday    = (todayDate.getDay() + 6) % 7; // 0 = понедельник
const monday      = new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate() - dowToday);
const nextMonday  = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + 7);
const mondayKey   = localDateStr(monday);
const tomorrow    = new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate() + 1);
const dayFraction = Math.min(Math.max((now - todayDate) / (tomorrow - todayDate), 0), 1); // какая доля сегодняшнего дня уже прошла (в день перехода на летнее время он 23/25ч)

const msLeft    = Math.max(nextMonday - now, 0);
const daysLeft  = Math.floor(msLeft / 86400000);
const hoursLeft = Math.floor((msLeft % 86400000) / 3600000);
const minsLeft  = Math.floor((msLeft % 3600000) / 60000);
const resetLabel = daysLeft > 0 ? `${{daysLeft}}d ${{hoursLeft}}h`
                 : hoursLeft > 0 ? `${{hoursLeft}}h ${{minsLeft}}m`
                 : `${{minsLeft}}m`;

const xpByDate = {{}};
for (const p of pages) {{
  const ds = toDateStr(p.date) || p.file.name;
  if (ds) xpByDate[ds] = Number(p.xp) || 0;
}}
let weekXP = 0;
for (let i = 0; i <= dowToday; i++) {{
  const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i);
  weekXP += xpByDate[localDateStr(d)] || 0;
}}

// Точка отсчёта проекта
let projectStart = null;
for (const p of pages) {{
  const ds = toDateStr(p.date) || p.file.name;
  if (!ds) continue;
  const d = new Date(ds + "T00:00:00");
  if (!projectStart || d < projectStart) projectStart = d;
}}
if (!projectStart) projectStart = todayDate;
const daysSinceStart = Math.max(1, Math.round((todayDate - projectStart) / 86400000) + 1);


function hashStr(s) {{
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {{ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }}
  return h >>> 0;
}}
function rng(seed) {{
  let t = seed >>> 0;
  t = (t + 0x6d2b79f5) | 0;
  let r = Math.imul(t ^ (t >>> 15), 1 | t);
  r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
  return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
}}

// XP-эквивалент по часам
const XP_PER_HOUR_    = {XP_PER_HOUR};
const TOP_LANG_BONUS_ = {TOP_LANG_BONUS};
const ASSUMED_STREAK  = 7;
const STREAK_MULT     = 1 + Math.min(ASSUMED_STREAK, 10) * 0.05;
const STREAK_BONUS_   = Math.min(ASSUMED_STREAK, 3) * {STREAK_BONUS_PER_DAY};
const STREAK_ACH_     = {ACHIEVEMENT_STREAK_BONUS[7]};
function hourAchBonus(h) {{
  if (h >= 6) return {ACHIEVEMENT_HOUR_BONUS[6]};
  if (h >= 5) return {ACHIEVEMENT_HOUR_BONUS[5]};
  if (h >= 3) return {ACHIEVEMENT_HOUR_BONUS[3]};
  if (h >= 1) return {ACHIEVEMENT_HOUR_BONUS[1]};
  return 0;
}}
function xpForHours(h) {{
  if (h <= 0) return 0;
  const core = h * XP_PER_HOUR_ * TOP_LANG_BONUS_ * STREAK_MULT + STREAK_BONUS_;
  return Math.max(0, Math.round(core + STREAK_ACH_ + hourAchBonus(h)));
}}

const RIVAL_POOL = [
  {{ name: "AutoCommitBot",  code: "1f916",                debutDay:  0, hours: 0.7, activeChance: 0.90, volatility: 0.08, baseStreak: 25, streakVar:  7 }},
  {{ name: "NullPointerJoe", code: "1f9d1-200d-1f4bb",     debutDay:  0, hours: 1.4, activeChance: 0.55, volatility: 0.30, baseStreak:  3, streakVar:  4 }},
  {{ name: "FoxCommit",      code: "1f98a",                debutDay: 55, hours: 2.1, activeChance: 0.60, volatility: 0.30, baseStreak:  5, streakVar:  5 }},
  {{ name: "RecursiveRex",   code: "1f9d9-200d-2642-fe0f", debutDay:  0, hours: 3.6, activeChance: 0.65, volatility: 0.35, baseStreak:  7, streakVar:  5 }},
  {{ name: "DragonScale.dev",code: "1f409",                debutDay: 30, hours: 4.4, activeChance: 0.63, volatility: 0.35, baseStreak: 14, streakVar:  8 }},
  {{ name: "GhostWriter404", code: "1f47b",                debutDay: 12, hours: 5.0, activeChance: 0.66, volatility: 0.45, baseStreak:  8, streakVar:  6 }},
  {{ name: "SyntaxQueen",    code: "1f9d9-200d-2640-fe0f", debutDay:  0, hours: 5.5, activeChance: 0.72, volatility: 0.45, baseStreak: 18, streakVar:  8 }},
  {{ name: "ByteNinja_88",   code: "1f977",                debutDay:  0, hours: 6.8, activeChance: 0.80, volatility: 0.60, baseStreak: 22, streakVar: 10 }},
];


const SLUMP_BASE = 0.12, SLUMP_SLOPE = 0.18;   // доля spad-дней:   0.12…0.30
const SPIKE_BASE = 0.06, SPIKE_SLOPE = 0.34;   // доля spike-дней:  0.06…0.40
const SLUMP_MIN = 0.2,  SLUMP_MAX = 0.55;      // spad:   20-55% от обычных часов
const SPIKE_MIN = 1.5,  SPIKE_MAX = 3.3;       // spike: 150-330% от обычных часов
const NORMAL_MIN = 0.75, NORMAL_MAX = 1.35;    // обычный день: 75-135%
const MAX_DAY_HOURS = 16;                      // предохранитель от абсурдных значений

function dayMultiplier(name, key, volatility) {{
  const slumpP = SLUMP_BASE + volatility * SLUMP_SLOPE;
  const spikeP = SPIKE_BASE + volatility * SPIKE_SLOPE;
  const tierRoll = rng(hashStr(name + "|tier|" + key));
  const amtRoll  = rng(hashStr(name + "|amt|" + key));
  if (tierRoll < slumpP) return SLUMP_MIN + amtRoll * (SLUMP_MAX - SLUMP_MIN);
  if (tierRoll < slumpP + spikeP) return SPIKE_MIN + amtRoll * (SPIKE_MAX - SPIKE_MIN);
  return NORMAL_MIN + amtRoll * (NORMAL_MAX - NORMAL_MIN);
}}

function simulateRival(r) {{
  let xp = 0;
  for (let i = 0; i <= dowToday; i++) {{
    const d   = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i);
    const key = localDateStr(d);

    // До дебюта соперника и до старта проекта часы не набегают
    const dayIdx = Math.round((d - projectStart) / 86400000) + 1;
    if (dayIdx < Math.max(1, r.debutDay)) continue;

    // Кодил ли он в этот день?
    if (rng(hashStr(r.name + "|act|" + key)) >= r.activeChance) continue;

    let hours = Math.min(r.hours * dayMultiplier(r.name, key, r.volatility), MAX_DAY_HOURS);
    if (i === dowToday) hours *= dayFraction; // сегодняшний день набегает плавно с 00:00
    xp += xpForHours(hours);
  }}

  const streakKey   = r.name + "|streak|" + mondayKey;
  const streakNoise = Math.round((rng(hashStr(streakKey)) * 2 - 1) * r.streakVar);
  const streak = Math.max(1, r.baseStreak + streakNoise);

  return {{ name: r.name, code: r.code, xp: Math.round(xp), streak }};
}}

const activeRivals = RIVAL_POOL
  .filter(r => daysSinceStart >= r.debutDay)
  .map(simulateRival);

const you = {{ name: "You", code: "1f9d1-200d-1f4bb", xp: weekXP, streak: youStreak, isYou: true }};

const board = [...activeRivals, you].sort((a, b) =>
  (b.xp - a.xp) || (b.streak - a.streak) || a.name.localeCompare(b.name));
const top3  = board.slice(0, 3);
const rest  = board.slice(3);

function emoji(code, size) {{
  const s = size || 24;
  return `<img src="https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-160/${{code}}.png" width="${{s}}" height="${{s}}" style="display:block" alt=""/>`;
}}
function fmtXP(v) {{ return Math.round(v).toLocaleString("en-US"); }}

const PODIUM_STYLE = {{
  1: {{ avatarPx: 76, imgPx: 48, blockH: 118, ring: "#4ade80", ringGlow: "rgba(74,222,128,0.55)",
       nameSize: 17, blockBg: "linear-gradient(180deg,#173321 0%,#0a140d 100%)", blockBorder: "rgba(74,222,128,0.4)",
       numClr: "#4ade80", numShadow: "0 0 16px rgba(74,222,128,0.6)", xpClr: "#bbf7d0", numSize: 29, xpSize: 13.5,
       pillBg: "rgba(74,222,128,0.16)", pillBorder: "rgba(74,222,128,0.45)", pillText: "#bbf7d0", pillGlow: "0 0 14px rgba(74,222,128,0.25)" }},
  2: {{ avatarPx: 64, imgPx: 40, blockH: 88, ring: "rgba(226,232,240,0.4)", ringGlow: "rgba(203,213,225,0.15)",
       nameSize: 15, blockBg: "linear-gradient(180deg,#20272c 0%,#12161a 100%)", blockBorder: "rgba(226,232,240,0.18)",
       numClr: "#e2e8f0", numShadow: "none", xpClr: "#c3cdd8", numSize: 23, xpSize: 12.5,
       pillBg: "rgba(226,232,240,0.1)", pillBorder: "rgba(226,232,240,0.22)", pillText: "#f1f5f9", pillGlow: "none" }},
  3: {{ avatarPx: 58, imgPx: 36, blockH: 64, ring: "rgba(251,191,110,0.5)", ringGlow: "rgba(251,191,110,0.18)",
       nameSize: 15, blockBg: "linear-gradient(180deg,#2a2015 0%,#160f08 100%)", blockBorder: "rgba(251,191,110,0.26)",
       numClr: "#fbbf6e", numShadow: "none", xpClr: "#e3c395", numSize: 20, xpSize: 12,
       pillBg: "rgba(251,191,110,0.12)", pillBorder: "rgba(251,191,110,0.3)", pillText: "#fde3bb", pillGlow: "none" }},
}};

function podiumSlot(entry, rank) {{
  const st = PODIUM_STYLE[rank];
  const youTag = entry.isYou
    ? `<div style="margin-top:5px;font-size:10.5px;font-weight:800;color:#4ade80;letter-spacing:0.6px">YOU</div>` : "";
  const crown = rank === 1
    ? `<img src="https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-160/1f3c6.png" width="30" height="30" style="margin-bottom:4px;filter:drop-shadow(0 0 10px rgba(250,204,21,0.7))"/>` : "";
  return `
  <div style="display:flex;flex-direction:column;align-items:center">
    ${{crown}}
    <div style="position:relative;width:${{st.avatarPx}}px;height:${{st.avatarPx}}px;border-radius:50%;background:radial-gradient(circle at 35% 30%, #182018, #0a0f0c);border:${{rank===1?"2.5px":"2px"}} solid ${{st.ring}};box-shadow:0 0 ${{rank===1?28:18}}px ${{st.ringGlow}};display:flex;align-items:center;justify-content:center;margin-bottom:10px">
      ${{emoji(entry.code, st.imgPx)}}
      <div style="position:absolute;bottom:-6px;right:-5px;width:23px;height:23px;border-radius:50%;background:#1c1c1f;border:1.5px solid ${{st.ring}};display:flex;align-items:center;justify-content:center;font-size:11.5px;font-weight:800;color:${{st.numClr}};font-family:-apple-system,sans-serif">${{rank}}</div>
    </div>
    <div style="font-size:${{st.nameSize}}px;font-weight:${{rank===1?800:700}};color:#ffffff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;white-space:nowrap;max-width:150px;overflow:hidden;text-overflow:ellipsis">${{entry.name}}</div>
    ${{youTag}}
    <div style="display:flex;align-items:center;gap:5px;margin-top:7px;background:${{st.pillBg}};border:1px solid ${{st.pillBorder}};border-radius:999px;padding:4px 11px;box-shadow:${{st.pillGlow}}">
      ${{emoji("1f525", 13)}}
      <span style="font-size:12.5px;font-weight:700;color:${{st.pillText}}">${{entry.streak}}d</span>
    </div>
    <div style="
      margin-top:10px;width:100%;height:${{st.blockH}}px;border-radius:${{rank===1?16:14}}px ${{rank===1?16:14}}px 0 0;
      background:${{st.blockBg}};border:1px solid ${{st.blockBorder}};border-bottom:none;
      display:flex;flex-direction:column;align-items:center;justify-content:flex-start;padding-top:${{rank===1?12:10}}px;
      box-shadow:inset 0 1px 0 rgba(255,255,255,0.08);
    ">
      <span style="font-size:${{st.numSize}}px;font-weight:800;color:${{st.numClr}};text-shadow:${{st.numShadow}}">${{rank}}</span>
      <span style="font-size:${{st.xpSize}}px;color:${{st.xpClr}};margin-top:3px;font-weight:${{rank===1?700:600}};font-family:-apple-system,sans-serif">${{fmtXP(entry.xp)}} XP</span>
    </div>
  </div>`;
}}

function listRow(entry, rank) {{
  const isYou = !!entry.isYou;
  const bg           = isYou ? "rgba(74,222,128,0.1)" : "rgba(255,255,255,0.03)";
  const border       = isYou ? "1.5px solid rgba(74,222,128,0.45)" : "1px solid rgba(255,255,255,0.07)";
  const shadow       = isYou ? "box-shadow:0 0 20px rgba(74,222,128,0.15);" : "";
  const rankClr      = isYou ? "#4ade80" : "#8f9c95";
  const xpClr        = isYou ? "#4ade80" : "#bbf7d0";
  const streakClr    = isYou ? "#a7f3c5" : "#93a49b";
  const avatarBorder = isYou ? "1.5px solid #4ade80" : "1px solid rgba(255,255,255,0.12)";
  const avatarGlow   = isYou ? "box-shadow:0 0 12px rgba(74,222,128,0.45);" : "";
  const nameTag      = isYou ? ` <span style="color:#4ade80;font-weight:700">· You</span>` : "";
  return `
  <div style="display:flex;align-items:center;gap:14px;background:${{bg}};border:${{border}};border-radius:16px;padding:12px 16px;${{shadow}}">
    <span style="font-size:14.5px;color:${{rankClr}};font-weight:${{isYou?800:700}};width:18px;text-align:center;font-family:-apple-system,sans-serif">${{rank}}</span>
    <div style="width:38px;height:38px;border-radius:50%;background:#12161a;border:${{avatarBorder}};display:flex;align-items:center;justify-content:center;flex-shrink:0;${{avatarGlow}}">
      ${{emoji(entry.code, 23)}}
    </div>
    <div style="flex:1;min-width:0">
      <div style="font-size:15.5px;font-weight:${{isYou?800:700}};color:#f4f7f5;font-family:-apple-system,BlinkMacSystemFont,sans-serif">${{entry.name}}${{nameTag}}</div>
      <div style="font-size:12px;color:${{streakClr}};margin-top:2px;display:flex;align-items:center;gap:4px">
        ${{emoji("1f525", 11)}} ${{entry.streak}}d streak
      </div>
    </div>
    <span style="font-size:16px;font-weight:800;color:${{xpClr}};font-family:-apple-system,sans-serif">${{fmtXP(entry.xp)}} XP</span>
  </div>`;
}}

const yourRank = board.findIndex(e => e.isYou) + 1;
const newestRival = activeRivals.filter(r => {{
  const profile = RIVAL_POOL.find(p => p.name === r.name);
  return profile.debutDay > 0 && (daysSinceStart - profile.debutDay) <= 2;
}}).sort((a, b) => a.name.localeCompare(b.name))[0];
const newArrivalBadge = newestRival
  ? `<span style="margin-left:8px;background:rgba(250,204,21,0.14);border:1px solid rgba(250,204,21,0.35);color:#fde68a;font-size:10.5px;font-weight:700;padding:3px 9px;border-radius:999px;white-space:nowrap">NEW: ${{newestRival.name}}</span>`
  : "";

let html = `
<div style="
  position:relative;
  font-family:'SF Mono','Consolas',monospace;
  background:linear-gradient(160deg,#0d1310 0%,#070a08 60%,#050705 100%);
  border:1px solid rgba(74,222,128,0.14);
  border-radius:24px;
  padding:26px 26px 24px;
  color:#e5e5e5;
  overflow:hidden;
  box-shadow:0 0 60px rgba(34,197,94,0.10), inset 0 0 60px rgba(34,197,94,0.03);
  margin:8px 0;
">
  <div style="position:absolute;top:-90px;left:-60px;width:280px;height:240px;background:radial-gradient(circle, rgba(74,222,128,0.30) 0%, transparent 70%);filter:blur(60px);pointer-events:none"></div>
  <div style="position:absolute;bottom:-110px;right:-60px;width:260px;height:230px;background:radial-gradient(circle, rgba(34,197,94,0.22) 0%, transparent 70%);filter:blur(60px);pointer-events:none"></div>
  <div style="
    position:absolute;inset:0;pointer-events:none;opacity:0.5;
    background-image:linear-gradient(rgba(74,222,128,0.05) 1px, transparent 1px),linear-gradient(90deg, rgba(74,222,128,0.05) 1px, transparent 1px);
    background-size:26px 26px;
    mask-image:radial-gradient(ellipse at 50% 0%, rgba(0,0,0,0.6) 0%, transparent 65%);
    -webkit-mask-image:radial-gradient(ellipse at 50% 0%, rgba(0,0,0,0.6) 0%, transparent 65%);
  "></div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
    <div>
      <div style="font-size:12px;letter-spacing:2.2px;color:rgba(134,239,172,0.75);font-weight:700">RIVAL CODERS</div>
      <div style="font-size:27px;font-weight:800;color:#ffffff;letter-spacing:-0.3px;margin-top:6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">Leaderboard</div>
    </div>
    <div style="background:rgba(74,222,128,0.12);border:1px solid rgba(74,222,128,0.32);border-radius:999px;padding:7px 15px;font-size:12.5px;color:#a7f3c5;font-weight:700;letter-spacing:0.4px;white-space:nowrap">WEEKLY XP</div>
  </div>
  <div style="position:relative;font-size:13.5px;color:rgba(190,205,197,0.75);margin-bottom:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">Fictional rivals · resets Mon 00:00 · in ${{resetLabel}}${{newArrivalBadge}}</div>

  <div style="position:relative;display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;align-items:end;margin-bottom:16px">
    ${{podiumSlot(top3[1], 2)}}
    ${{podiumSlot(top3[0], 1)}}
    ${{podiumSlot(top3[2], 3)}}
  </div>

  <div style="position:relative;height:1px;background:linear-gradient(90deg, transparent, rgba(74,222,128,0.35), transparent);margin-bottom:20px"></div>

  <div style="position:relative;display:flex;flex-direction:column;gap:8px;margin-bottom:6px">
    ${{rest.map((e, i) => listRow(e, i + 4)).join("")}}
  </div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:center;margin-top:16px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.08);font-size:12px;color:rgba(180,196,188,0.6);letter-spacing:0.3px;font-family:-apple-system,sans-serif">
    <span>${{board.length}} rivals · rank #${{yourRank}}</span>
    <span>Coding Progression System</span>
  </div>
</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## Top Weeks by XP

```dataviewjs
const MIN_HOURS = {MIN_HOURS_FOR_STREAK};

const pages = dv.pages('"daily"').where(p => p.date != null).array();


function toDateStr(val) {{
  if (!val) return null;
  if (typeof val === "string") return val.slice(0, 10);
  if (val.toFormat) return val.toFormat("yyyy-MM-dd");
  if (val instanceof Date) return localDateStr(val);
  return String(val).slice(0, 10);
}}
function localDateStr(d) {{
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${{y}}-${{m}}-${{day}}`;
}}
function parseLocalDate(dateStr) {{
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d); // локальная полночь, не UTC
}}
function mondayOf(d) {{
  const dow = (d.getDay() + 6) % 7; // 0 = понедельник
  const m = new Date(d);
  m.setDate(d.getDate() - dow);
  return m;
}}
function fmtShort(d) {{
  return d.toLocaleDateString("en-GB", {{ day: "2-digit", month: "short" }});
}}


const hoursByDate = {{}};
const xpByDate = {{}};
for (const p of pages) {{
  const ds = toDateStr(p.date);
  if (!ds) continue;
  hoursByDate[ds] = Number(p.coding_time) || 0;
  if (p.xp != null) xpByDate[ds] = Number(p.xp) || 0;
}}

const knownDates = Object.keys(hoursByDate).sort();

if (knownDates.length === 0) {{
  dv.paragraph("_No data yet — start coding!_");
}} else {{


const firstMonday = mondayOf(parseLocalDate(knownDates[0]));
const lastMonday  = mondayOf(parseLocalDate(knownDates[knownDates.length - 1]));

const weeks = [];
let cursor = new Date(firstMonday);
while (cursor <= lastMonday) {{
  const monday = new Date(cursor);
  const days = [];
  for (let i = 0; i < 7; i++) {{
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const ds = localDateStr(d);
    days.push({{ hours: hoursByDate[ds] || 0, xp: xpByDate[ds] || 0 }});
  }}

  const hours = days.reduce((s, d) => s + d.hours, 0);

  if (hours > 0) {{
    const xp = days.reduce((s, d) => s + d.xp, 0);

    let bestStreak = 0, curStreak = 0;
    for (const d of days) {{
      if (d.hours >= MIN_HOURS) {{ curStreak++; bestStreak = Math.max(bestStreak, curStreak); }}
      else {{ curStreak = 0; }}
    }}

    const sunday = new Date(monday); sunday.setDate(monday.getDate() + 6);
    weeks.push({{
      label: `${{fmtShort(monday)}} – ${{fmtShort(sunday)}}`,
      hours, xp, bestStreak,
    }});
  }}

  cursor.setDate(cursor.getDate() + 7);
}}

// Только 5 лучших недель за всё время
const sorted = weeks.sort((a,b) => b.xp - a.xp).slice(0, 5);

if (sorted.length === 0) {{
  dv.paragraph("_No coded weeks yet — log some hours to start ranking your weeks!_");
}} else {{

const recordXP = sorted[0].xp;
const avgXP    = Math.round(sorted.reduce((s,w) => s+w.xp, 0) / sorted.length);

// Apple-эмодзи (тот же битмап-сет, что и в остальных виджетах проекта)
function emoji(code, size) {{
  const s = size || 20;
  return `<img src="https://raw.githubusercontent.com/iamcal/emoji-data/master/img-apple-160/${{code}}.png" width="${{s}}" height="${{s}}" style="display:block" alt=""/>`;
}}


const RANK_STYLE = {{
  1: {{ border:"rgba(216,169,92,0.45)",  glow:"rgba(216,169,92,0.16)",  bg1:"rgba(216,169,92,0.09)",  bg2:"rgba(216,169,92,0.03)",
       badgeBorder:"rgba(216,169,92,0.5)",  badgeGlow:"rgba(216,169,92,0.30)", badgeBg:"rgba(216,169,92,0.12)", xpClr:"#f3dcae" }},
  2: {{ border:"rgba(214,120,84,0.38)",  glow:"rgba(214,120,84,0.12)",  bg1:"rgba(214,120,84,0.08)",  bg2:"rgba(214,120,84,0.02)",
       badgeBorder:"rgba(214,120,84,0.42)", badgeGlow:"rgba(214,120,84,0.22)", badgeBg:"rgba(214,120,84,0.10)", xpClr:"#f0c4ab" }},
  3: {{ border:"rgba(90,180,140,0.36)",  glow:"rgba(90,180,140,0.12)",  bg1:"rgba(90,180,140,0.08)",  bg2:"rgba(90,180,140,0.02)",
       badgeBorder:"rgba(90,180,140,0.42)", badgeGlow:"rgba(90,180,140,0.22)", badgeBg:"rgba(90,180,140,0.10)", xpClr:"#bfe6d3" }},
  4: {{ border:"rgba(100,130,210,0.30)", glow:"rgba(100,130,210,0.10)", bg1:"rgba(100,130,210,0.07)", bg2:"rgba(100,130,210,0.02)",
       badgeBorder:"rgba(100,130,210,0.4)", badgeGlow:"rgba(100,130,210,0.2)", badgeBg:"rgba(100,130,210,0.10)", xpClr:"#c4d0f2" }},
  5: {{ border:"rgba(180,110,210,0.28)", glow:"rgba(180,110,210,0.10)", bg1:"rgba(180,110,210,0.07)", bg2:"rgba(180,110,210,0.02)",
       badgeBorder:"rgba(180,110,210,0.4)", badgeGlow:"rgba(180,110,210,0.2)", badgeBg:"rgba(180,110,210,0.10)", xpClr:"#e5c9f2" }},
}};
const MEDAL_CODES = {{ 1: "1f947", 2: "1f948", 3: "1f949" }};

function rankBadge(rank, st) {{
  const size = rank === 1 ? 46 : 40;
  const inner = MEDAL_CODES[rank]
    ? emoji(MEDAL_CODES[rank], rank === 1 ? 30 : 26)
    : `<span style="font-size:15px;font-weight:800;color:${{st.xpClr}}">${{rank}}</span>`;
  return `
  <div style="
    width:${{size}}px;height:${{size}}px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;flex-shrink:0;
    border:1.5px solid ${{st.badgeBorder}};
    background:${{st.badgeBg}};
    box-shadow:0 0 ${{rank===1?16:12}}px ${{st.badgeGlow}};
  ">${{inner}}</div>`;
}}

function weekRow(w, rank) {{
  const st = RANK_STYLE[rank];
  const crown = rank === 1
    ? `<div style="position:absolute;top:-15px;left:33px">${{emoji("1f451",24)}}</div>` : "";
  const xpSize = rank === 1 ? 21 : 18;
  const rowGlow = rank === 1 ? 26 : (rank <= 3 ? 20 : 16);
  return `
  <div style="
    display:flex;align-items:center;gap:14px;
    border-radius:20px;padding:13px 16px 13px 13px;position:relative;
    border:1.5px solid ${{st.border}};
    background:linear-gradient(100deg, ${{st.bg1}}, ${{st.bg2}});
    box-shadow:0 0 ${{rowGlow}}px ${{st.glow}}, inset 0 1px 0 rgba(255,255,255,0.03);
  ">
    ${{crown}}
    ${{rankBadge(rank, st)}}
    <div style="flex:1;min-width:0">
      <div style="font-size:15.5px;font-weight:800;color:#f0eee9">${{w.label}}</div>
      <div style="font-size:11.5px;color:rgba(230,225,215,0.4);margin-top:2px;font-weight:600;display:flex;align-items:center;gap:4px">
        ${{emoji("1f525",12)}}${{w.bestStreak}}d streak · ${{w.hours.toFixed(1)}}h coded
      </div>
    </div>
    <div style="text-align:right;flex-shrink:0">
      <span style="font-size:${{xpSize}}px;font-weight:800;letter-spacing:-0.2px;color:${{st.xpClr}}">${{w.xp}}</span><span style="font-size:10.5px;color:rgba(230,225,215,0.4);font-weight:700;margin-left:2px">XP</span>
    </div>
  </div>`;
}}

let html = `
<div style="
  position:relative;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:linear-gradient(165deg, rgba(255,255,255,0.045) 0%, rgba(255,255,255,0.015) 100%);
  border:1.5px solid rgba(255,255,255,0.09);
  border-radius:32px;
  padding:26px 24px 22px;
  overflow:hidden;
  box-shadow:0 0 60px rgba(255,180,70,0.06), 0 30px 70px rgba(0,0,0,0.55);
  margin:10px 0;
">
  <div style="position:absolute;top:-100px;right:-60px;width:240px;height:240px;border-radius:50%;background:rgba(255,190,80,0.14);filter:blur(60px);pointer-events:none;opacity:0.5"></div>
  <div style="position:absolute;bottom:-90px;left:-60px;width:220px;height:220px;border-radius:50%;background:rgba(70,200,150,0.10);filter:blur(60px);pointer-events:none;opacity:0.5"></div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px">
    <div>
      <div style="display:inline-flex;align-items:center;gap:6px;font-size:10.5px;letter-spacing:1.4px;color:#d8a95c;font-weight:800;background:rgba(216,169,92,0.10);border:1.5px solid rgba(216,169,92,0.35);border-radius:999px;padding:5px 12px;margin-bottom:10px">
        ${{emoji("1f947",13)}} ALL-TIME RANKING
      </div>
      <div style="font-size:24px;font-weight:800;color:#f2f1ee;letter-spacing:-0.4px">Top Weeks by XP</div>
      <div style="font-size:13px;color:rgba(230,225,215,0.45);margin-top:6px;font-weight:600">Your ${{sorted.length}} strongest week${{sorted.length===1?"":"s"}} so far</div>
    </div>
    <div style="
      width:50px;height:50px;border-radius:17px;flex-shrink:0;
      background:linear-gradient(160deg, rgba(216,169,92,0.16), rgba(216,169,92,0.05));
      border:1.5px solid rgba(216,169,92,0.35);
      box-shadow:0 0 22px rgba(216,169,92,0.20);
      display:flex;align-items:center;justify-content:center;
    ">${{emoji("1f3c6",28)}}</div>
  </div>

  <div style="position:relative;display:flex;gap:10px;margin-bottom:20px">
    <div style="flex:1;background:rgba(255,255,255,0.03);border:1.5px solid rgba(216,169,92,0.30);box-shadow:0 0 16px rgba(216,169,92,0.08) inset;border-radius:16px;padding:12px 16px">
      <div style="font-size:10px;letter-spacing:1px;color:rgba(230,225,215,0.35);font-weight:700">RECORD WEEK</div>
      <div style="font-size:20px;font-weight:800;color:#f0eee9;margin-top:4px;letter-spacing:-0.3px">${{recordXP}} XP</div>
    </div>
    <div style="flex:1;background:rgba(255,255,255,0.03);border:1.5px solid rgba(90,180,140,0.30);box-shadow:0 0 16px rgba(90,180,140,0.08) inset;border-radius:16px;padding:12px 16px">
      <div style="font-size:10px;letter-spacing:1px;color:rgba(230,225,215,0.35);font-weight:700">AVERAGE (TOP ${{sorted.length}})</div>
      <div style="font-size:20px;font-weight:800;color:#f0eee9;margin-top:4px;letter-spacing:-0.3px">${{avgXP}} XP</div>
    </div>
  </div>

  <div style="position:relative;display:flex;flex-direction:column;gap:11px">
    ${{sorted.map((w,i) => weekRow(w, i+1)).join("")}}
  </div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:center;margin-top:20px;padding-top:16px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:rgba(230,225,215,0.32);letter-spacing:0.2px;font-weight:700">
    <span>Ranked by weekly XP total</span>
    <span>Coding Progression System</span>
  </div>
</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
}}
}}
```

---

## Daily Average

```dataviewjs
const todayHours = Number(dv.current().coding_time) || 0;

function localDateStr(d) {{
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${{y}}-${{m}}-${{day}}`;
}}

const allPages = dv.pages('"daily"').where(p => p.coding_time != null && p.date != null).array();
const byDate = {{}};
for (const p of allPages) {{
  const key = String(p.date).slice(0, 10);
  byDate[key] = Number(p.coding_time) || 0;
}}

// "Today" comes from this note's own date field (not system clock), so the
// widget stays consistent regardless of when Obsidian happens to re-render it.
const todayStr = String(dv.current().date).slice(0, 10);
const [ty, tm, td] = todayStr.split("-").map(Number);
const todayDate = new Date(ty, tm - 1, td);

// Rolling 7-day window ending today (inclusive) — divides by all 7 calendar
// days, not just days with logged data, matching WakaTime's own "daily
// average" definition.
const WINDOW = 7;
let windowSum = 0;
let bestDay = {{ date: todayDate, hours: -1 }};
for (let i = 0; i < WINDOW; i++) {{
  const d = new Date(todayDate);
  d.setDate(todayDate.getDate() - i);
  const key = localDateStr(d);
  const h = (key === todayStr) ? todayHours : (byDate[key] || 0);
  windowSum += h;
  if (h > bestDay.hours) bestDay = {{ date: d, hours: h }};
}}
const avgHours = windowSum / WINDOW;

const pctChange = avgHours > 0
  ? Math.round(((todayHours - avgHours) / avgHours) * 100)
  : (todayHours > 0 ? 100 : 0);
const isUp = pctChange >= 0;

function ordinal(n) {{
  const s = ["th","st","nd","rd"], v = n % 100;
  return n + (s[(v-20)%10] || s[v] || s[0]);
}}
// Fixed 3-letter labels instead of toLocaleDateString — some Electron/webkit
// builds render "Sept" instead of "Sep" for en-GB locale, which would drift
// from the intended "Sep 8th" style.
const WEEKDAYS_SHORT = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const MONTHS_SHORT    = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const weekdayShort = WEEKDAYS_SHORT[bestDay.date.getDay()];
const monthShort   = MONTHS_SHORT[bestDay.date.getMonth()];
const mostActiveLabel = `${{weekdayShort}} ${{monthShort}} ${{ordinal(bestDay.date.getDate())}}`;

function fmtH(h) {{
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  if (hrs === 0) return `${{mins}} min`;
  if (mins === 0) return `${{hrs}} hr`;
  return `${{hrs}} hr ${{mins}} min`;
}}

// Gauge geometry: dome opening downward, 220° sweep
const START_ANGLE = 200;
const END_ANGLE   = -20;
const SWEEP_TOTAL = START_ANGLE - END_ANGLE;
const MAX_H = 8; // full-scale hours for the gauge
const gaugeVal = Math.min(todayHours / MAX_H, 1);
const fillAngleEnd = START_ANGLE - gaugeVal * SWEEP_TOTAL;

function pt(cx, cy, r, angleDeg) {{
  const rad = angleDeg * Math.PI / 180;
  return [cx + r * Math.cos(rad), cy - r * Math.sin(rad)];
}}
function arcPath(cx, cy, r, a0, a1) {{
  const [x0, y0] = pt(cx, cy, r, a0);
  const [x1, y1] = pt(cx, cy, r, a1);
  const large = (a0 - a1) > 180 ? 1 : 0;
  return `M ${{x0.toFixed(2)}} ${{y0.toFixed(2)}} A ${{r}} ${{r}} 0 ${{large}} 1 ${{x1.toFixed(2)}} ${{y1.toFixed(2)}}`;
}}

const W = 400, H = 240;
const cx = W / 2, cy = 132;
const R_OUTER = 122, R_INNER = 95;
const R_MID = (R_OUTER + R_INNER) / 2;
const SW = R_OUTER - R_INNER;

const [kx, ky] = pt(cx, cy, R_MID, fillAngleEnd);
const trackPath = arcPath(cx, cy, R_MID, START_ANGLE, END_ANGLE);
const fillPath  = gaugeVal > 0.01 ? arcPath(cx, cy, R_MID, START_ANGLE, fillAngleEnd) : "";

let statusLabel, statusColor;
if      (pctChange >= 100) {{ statusLabel = pctChange + "% Increase";  statusColor = "#ff4436"; }}
else if (pctChange >= 50)  {{ statusLabel = pctChange + "% Increase";  statusColor = "#ff6b44"; }}
else if (pctChange >= 0)   {{ statusLabel = pctChange + "% Increase";  statusColor = "#4ade80"; }}
else                        {{ statusLabel = Math.abs(pctChange) + "% Below Avg"; statusColor = "#93a3d8"; }}

let ticks = "";
const N_TICKS = 24;
for (let i = 0; i <= N_TICKS; i++) {{
  const angle = START_ANGLE - (i / N_TICKS) * SWEEP_TOTAL;
  const isMaj = i % 4 === 0;
  const r1 = R_INNER + 2;
  const r2 = R_INNER + (isMaj ? 12 : 6);
  const [x1,y1] = pt(cx,cy,r1,angle);
  const [x2,y2] = pt(cx,cy,r2,angle);
  ticks += `<line x1="${{x1.toFixed(1)}}" y1="${{y1.toFixed(1)}}" x2="${{x2.toFixed(1)}}" y2="${{y2.toFixed(1)}}"
    stroke="rgba(255,255,255,${{isMaj ? "0.13" : "0.05"}})" stroke-width="${{isMaj ? "1.6" : "1"}}" stroke-linecap="round"/>`;
}}

const svgDefs = `
<defs>
  <linearGradient id="fillGrad" x1="0%" y1="100%" x2="100%" y2="0%">
    <stop offset="0%"   stop-color="#ff2818"/>
    <stop offset="55%"  stop-color="#ff4d24"/>
    <stop offset="100%" stop-color="#ff8038"/>
  </linearGradient>
  <filter id="arcGlowBig" x="-60%" y="-60%" width="220%" height="220%">
    <feGaussianBlur stdDeviation="11" result="g"/>
    <feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="arcGlowSm" x="-30%" y="-30%" width="160%" height="160%">
    <feGaussianBlur stdDeviation="4" result="g"/>
    <feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <radialGradient id="knobBody" cx="34%" cy="26%" r="68%">
    <stop offset="0%"   stop-color="#ffffff"/>
    <stop offset="32%"  stop-color="#efedf7"/>
    <stop offset="68%"  stop-color="#c2bcda"/>
    <stop offset="100%" stop-color="#7c74a0"/>
  </radialGradient>
  <radialGradient id="knobInner" cx="38%" cy="30%" r="60%">
    <stop offset="0%"   stop-color="#ffffff"/>
    <stop offset="55%"  stop-color="#d4cef0"/>
    <stop offset="100%" stop-color="#8e86b8"/>
  </radialGradient>
  <filter id="knobGlow" x="-140%" y="-140%" width="380%" height="380%">
    <feGaussianBlur stdDeviation="12" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="knobGlowHot" x="-160%" y="-160%" width="420%" height="420%">
    <feGaussianBlur stdDeviation="18" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <filter id="knobShadow" x="-60%" y="-60%" width="220%" height="220%">
    <feGaussianBlur stdDeviation="3.5" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <linearGradient id="trackGrad" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="#241a20"/>
    <stop offset="100%" stop-color="#180f14"/>
  </linearGradient>
</defs>`;

const svgInner = svgDefs + `
<path d="${{trackPath}}" fill="none" stroke="#3a1018" stroke-width="${{SW+10}}" stroke-linecap="round" opacity="0.35" filter="url(#arcGlowSm)"/>
<path d="${{trackPath}}" fill="none" stroke="url(#trackGrad)" stroke-width="${{SW}}" stroke-linecap="round"/>
<path d="${{trackPath}}" fill="none" stroke="rgba(255,60,30,0.12)" stroke-width="${{SW}}" stroke-linecap="round"/>
${{ticks}}
${{fillPath ? `<path d="${{fillPath}}" fill="none" stroke="#ff3018" stroke-width="${{SW+34}}" stroke-linecap="round" opacity="0.14" filter="url(#arcGlowBig)"/>` : ""}}
${{fillPath ? `<path d="${{fillPath}}" fill="none" stroke="#ff4a26" stroke-width="${{SW+14}}" stroke-linecap="round" opacity="0.30" filter="url(#arcGlowSm)"/>` : ""}}
${{fillPath ? `<path d="${{fillPath}}" fill="none" stroke="url(#fillGrad)" stroke-width="${{SW}}" stroke-linecap="round" opacity="0.97"/>` : ""}}
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="42" fill="rgba(255,60,25,0.16)" filter="url(#knobGlowHot)"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="30" fill="rgba(255,70,30,0.38)" filter="url(#knobGlow)"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{(ky+2.2).toFixed(2)}}" r="17" fill="rgba(0,0,0,0.5)" filter="url(#knobShadow)"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="17" fill="url(#knobBody)"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="17" fill="none" stroke="rgba(255,255,255,0.7)" stroke-width="1.3"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="17" fill="none" stroke="rgba(255,90,50,0.55)" stroke-width="2.4" filter="url(#knobGlow)"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="9.5" fill="url(#knobInner)"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="9.5" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="0.8"/>
<ellipse cx="${{(kx-4.8).toFixed(2)}}" cy="${{(ky-5.4).toFixed(2)}}" rx="5" ry="3.1" fill="rgba(255,255,255,0.9)" transform="rotate(-28 ${{kx.toFixed(2)}} ${{ky.toFixed(2)}})"/>
<ellipse cx="${{(kx+3.5).toFixed(2)}}" cy="${{(ky+6).toFixed(2)}}" rx="6" ry="3.5" fill="rgba(255,120,70,0.35)" transform="rotate(-28 ${{kx.toFixed(2)}} ${{ky.toFixed(2)}})"/>
<circle cx="${{kx.toFixed(2)}}" cy="${{ky.toFixed(2)}}" r="3" fill="rgba(95,88,124,0.9)"/>
`;

const arrowSVG = isUp
  ? `<svg width="20" height="20" viewBox="0 0 24 24"><path d="M12 4L4 14h5v6h6v-6h5z" fill="${{statusColor}}"/></svg>`
  : `<svg width="20" height="20" viewBox="0 0 24 24"><path d="M12 20L4 10h5V4h6v6h5z" fill="${{statusColor}}"/></svg>`;

const html = `
<div style="
  width:100%;
  box-sizing:border-box;
  background:
    radial-gradient(ellipse 500px 260px at 50% -8%, rgba(120,20,15,0.32) 0%, transparent 60%),
    radial-gradient(ellipse 380px 300px at 8% 105%, rgba(90,15,20,0.28) 0%, transparent 62%),
    radial-gradient(ellipse 340px 280px at 96% 90%, rgba(140,30,20,0.22) 0%, transparent 60%),
    linear-gradient(155deg,#151016 0%,#0e0a10 45%,#0a070c 100%);
  border:1.5px solid rgba(255,65,35,0.55);
  border-radius:28px;
  padding:26px 28px 24px;
  position:relative;
  overflow:hidden;
  margin:10px 0;
  box-shadow:
    0 0 0 1px rgba(255,50,20,0.12),
    0 0 40px rgba(255,45,20,0.35),
    0 0 90px rgba(255,35,15,0.22),
    0 32px 80px rgba(0,0,0,0.8),
    inset 0 1px 0 rgba(255,255,255,0.06),
    inset 0 0 60px rgba(255,40,20,0.05);
">
  <div style="
    position:absolute;inset:0;pointer-events:none;
    background-image:linear-gradient(rgba(255,50,20,0.10) 1px,transparent 1px),linear-gradient(90deg,rgba(255,50,20,0.10) 1px,transparent 1px);
    background-size:28px 28px;
    mask-image:radial-gradient(ellipse at 50% 10%, rgba(0,0,0,0.9) 0%, transparent 58%);
    -webkit-mask-image:radial-gradient(ellipse at 50% 10%, rgba(0,0,0,0.9) 0%, transparent 58%);
  "></div>
  <div style="position:absolute;top:-70px;left:-50px;width:280px;height:280px;background:radial-gradient(circle,rgba(255,45,20,0.32) 0%,transparent 70%);filter:blur(55px);pointer-events:none"></div>
  <div style="position:absolute;bottom:-80px;right:-40px;width:260px;height:220px;background:radial-gradient(circle,rgba(255,90,35,0.20) 0%,transparent 70%);filter:blur(60px);pointer-events:none"></div>
  <div style="position:absolute;top:40%;left:50%;transform:translate(-50%,-50%);width:340px;height:220px;background:radial-gradient(ellipse,rgba(255,60,25,0.14) 0%,transparent 68%);filter:blur(50px);pointer-events:none"></div>
  <div style="
    position:absolute;inset:-1.5px;border-radius:28px;padding:1.5px;pointer-events:none;
    background:linear-gradient(155deg, rgba(255,90,50,0.6), rgba(255,40,20,0.1) 30%, rgba(255,40,20,0.1) 70%, rgba(255,90,50,0.5));
    -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite:xor; mask-composite:exclude;
  "></div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">
    <span style="font-size:11px;color:rgba(220,205,210,0.55);letter-spacing:0.04em">WakaTime Data · Daily Average</span>
    <span style="background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:3px 12px;font-size:11px;color:rgba(203,213,225,0.8)">7 Days</span>
  </div>

  <div style="position:relative;text-align:center;margin-bottom:2px;margin-top:10px">
    <div style="font-size:32px;font-weight:900;color:#fbfbff;letter-spacing:-0.5px;line-height:1;text-shadow:0 0 22px rgba(255,60,30,0.35)">${{fmtH(todayHours)}}</div>
    <div style="font-size:11px;color:rgba(220,205,210,0.42);letter-spacing:2px;margin-top:5px;font-weight:700">TODAY</div>
  </div>

  <div style="position:relative;text-align:center;margin:4px 0 -6px;">
    <svg width="${{W}}" height="${{H}}" viewBox="0 0 ${{W}} ${{H}}" style="overflow:visible;max-width:100%;height:auto;display:inline-block">
      ${{svgInner}}
    </svg>
  </div>

  <div style="position:relative;display:flex;align-items:center;justify-content:center;gap:8px;margin-bottom:20px;">
    ${{arrowSVG}}
    <span style="font-size:17px;font-weight:800;color:${{statusColor}};letter-spacing:0.1px;text-shadow:0 0 16px ${{statusColor}}66">${{statusLabel}}</span>
  </div>

  <div style="position:relative;height:1px;background:linear-gradient(90deg,transparent,rgba(255,70,30,0.5),transparent);margin-bottom:16px;box-shadow:0 0 8px rgba(255,60,25,0.3)"></div>

  <div style="position:relative;display:flex;gap:10px;">
    <div style="flex:1;background:linear-gradient(160deg,rgba(255,60,25,0.08),rgba(255,60,25,0.02));border:1px solid rgba(255,60,25,0.28);border-radius:16px;padding:13px 16px;text-align:center;box-shadow:inset 0 1px 0 rgba(255,255,255,0.05), 0 0 16px rgba(255,50,20,0.08);">
      <div style="font-size:10px;color:rgba(220,205,210,0.42);letter-spacing:1.3px;font-weight:700;margin-bottom:5px;">DAILY AVG · 7D</div>
      <div style="font-size:18px;font-weight:800;color:#f2eef4;">${{fmtH(avgHours)}}</div>
    </div>
    <div style="flex:1;background:linear-gradient(160deg,rgba(255,60,25,0.08),rgba(255,60,25,0.02));border:1px solid rgba(255,60,25,0.28);border-radius:16px;padding:13px 16px;text-align:center;box-shadow:inset 0 1px 0 rgba(255,255,255,0.05), 0 0 16px rgba(255,50,20,0.08);">
      <div style="font-size:10px;color:rgba(220,205,210,0.42);letter-spacing:1.3px;font-weight:700;margin-bottom:5px;">MOST ACTIVE · 7D</div>
      <div style="font-size:14.5px;font-weight:800;color:#f2eef4;">${{mostActiveLabel}}</div>
    </div>
  </div>
</div>`;

const container = dv.el("div", "");
container.innerHTML = html;

```

---

## Activity (30 Days)

```dataviewjs
const pages = dv.pages('"daily"').where(p => p.coding_time != null).array();

function localDateStr(d) {{
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${{y}}-${{m}}-${{day}}`;
}}

const byDate = {{}};
for (const p of pages) {{
  const key = String(p.date).slice(0, 10);
  byDate[key] = Number(p.coding_time) || 0;
}}

const today = new Date();
const todayKey = localDateStr(today);
const days = [];
for (let i = 29; i >= 0; i--) {{
  const d = new Date(today); d.setDate(d.getDate() - i);
  days.push(localDateStr(d));
}}

const allTimeHours = pages.reduce((s, p) => s + (Number(p.coding_time) || 0), 0);
const todayHours   = byDate[todayKey] || 0;
const idleHours    = Math.max(24 - todayHours, 0);
const maxDay       = Math.max(...days.map(d => byDate[d] || 0), 0.1);
const dayLabel     = today.toLocaleDateString("en-US", {{ weekday: "long" }});

// Явно различимые ступени цвета — не плавный градиент альфы, а отдельные
// именованные оттенки, чтобы соседние уровни активности не сливались.
// Тускло-приглушённый -> ярко-мятный по мере роста часов.
const LEVELS = [
  {{ limit: 1,   color: [52, 78, 71]   }}, // <1h  — тусклый приглушённый
  {{ limit: 3,   color: [45, 125, 103] }}, // 1-3h — заметно ярче
  {{ limit: 5,   color: [34, 176, 133] }}, // 3-5h — насыщенный зелёный
  {{ limit: 7,   color: [52, 220, 165] }}, // 5-7h — яркий мятный
  {{ limit: Infinity, color: [140, 255, 214] }}, // 7h+ — максимально яркий
];
const EMPTY_BG = "#141518";

function colorFor(h) {{
  if (h <= 0) return null;
  for (const lvl of LEVELS) {{
    if (h < lvl.limit) return `rgb(${{lvl.color[0]}},${{lvl.color[1]}},${{lvl.color[2]}})`;
  }}
  const last = LEVELS[LEVELS.length - 1].color;
  return `rgb(${{last[0]}},${{last[1]}},${{last[2]}})`;
}}

const cols = 10;
const cellSize = 46;
const gap = 8;

// Сборка HTML
let html = `
<div style="
  font-family:'SF Mono','Consolas',monospace;
  background:linear-gradient(160deg,#0d0d0f 0%,#08080a 100%);
  border:1px solid rgba(255,255,255,0.06);
  border-radius:20px;
  padding:22px 22px 20px;
  color:#e5e5e5;
  box-shadow:0 0 40px rgba(0,0,0,0.4);
  margin:8px 0;
">`;

// Верхний бокс с общим числом часов
html += `
<div style="
  border:1px solid rgba(255,255,255,0.16);
  border-radius:10px;
  padding:14px 18px;
  display:flex;justify-content:space-between;align-items:center;
  margin-bottom:18px;
">
  <span style="font-size:13px;color:#cfd2d8;letter-spacing:0.2px">Coding hours logged:</span>
  <span style="font-size:15px;font-weight:700;color:#f4f4f6">${{allTimeHours.toFixed(1)}}</span>
</div>`;

// Строка Today | Active | Idle
html += `
<div style="display:flex;align-items:baseline;gap:14px;margin-bottom:20px;flex-wrap:wrap">
  <span style="font-size:14px;font-weight:700;color:#f4f4f6">${{dayLabel}}</span>
  <span style="font-size:13px;color:#4a4a52">|</span>
  <span style="font-size:13px;color:#9a9aa4">Active: <strong style="color:#6ee7b7;font-size:14px">${{todayHours.toFixed(1)}}h</strong></span>
  <span style="font-size:13px;color:#9a9aa4">Idle: <strong style="color:#e5e5e5;font-size:14px">${{idleHours.toFixed(1)}}h</strong></span>
</div>`;

// Сетка активности — ровно 30 ячеек, по одной на день (10 колонок x 3 ряда).
// Никаких подписей внутри клетки — дата и часы видны только по наведению.
html += `<div style="display:grid;grid-template-columns:repeat(${{cols}}, ${{cellSize}}px);gap:${{gap}}px">`;
days.forEach((day) => {{
  const h = byDate[day] || 0;
  const color = colorFor(h);
  const isToday = day === todayKey;
  const bg = color === null ? EMPTY_BG : color;
  const border = isToday
    ? "1.5px solid rgba(255,255,255,0.55)"
    : `1px solid ${{color === null ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.10)"}}`;

  html += `
  <div title="${{day}}: ${{h.toFixed(1)}}h" style="
    width:${{cellSize}}px;height:${{cellSize}}px;
    background:${{bg}};
    border:${{border}};
    border-radius:8px;
    display:flex;align-items:center;justify-content:center;
    cursor:default;
  ">
    ${{color === null ? `<span style="width:3px;height:3px;border-radius:50%;background:#2c2e34;display:block"></span>` : ""}}
  </div>`;
}});
html += `</div>`;

// Легенда интенсивности — те же цвета, что и в сетке
const legendSteps = [
  {{ label: "0h",    color: null }},
  {{ label: "<1h",   color: LEVELS[0].color }},
  {{ label: "1-3h",  color: LEVELS[1].color }},
  {{ label: "3-5h",  color: LEVELS[2].color }},
  {{ label: "5-7h",  color: LEVELS[3].color }},
  {{ label: "7h+",   color: LEVELS[4].color }},
];
html += `<div style="display:flex;align-items:center;gap:8px;margin-top:20px;flex-wrap:wrap">`;
html += `<span style="font-size:11px;color:#8b8b93;letter-spacing:0.5px;margin-right:4px">Intensity:</span>`;
legendSteps.forEach(step => {{
  const swatchBg = step.color === null ? EMPTY_BG : `rgb(${{step.color[0]}},${{step.color[1]}},${{step.color[2]}})`;
  const dot = step.color === null
    ? `<span style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:2.5px;height:2.5px;border-radius:50%;background:#2c2e34;display:block"></span>`
    : "";
  html += `
  <span style="display:flex;align-items:center;gap:5px">
    <span style="position:relative;width:13px;height:13px;border-radius:3px;background:${{swatchBg}};display:inline-block;border:1px solid rgba(255,255,255,0.06)">${{dot}}</span>
    <span style="font-size:10px;color:#6b6b73">${{step.label}}</span>
  </span>`;
}});
html += `</div>`;

// Подвал
html += `
<div style="display:flex;justify-content:space-between;margin-top:16px;padding-top:14px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#6b6b73">
  <span>Best day: <strong style="color:#a8a8b0">${{maxDay.toFixed(1)}}h</strong></span>
  <span>Coding Progression System</span>
</div>`;

html += `</div>`;

const container = dv.el("div", "");
container.innerHTML = html;
```

---

## XP (14 Days)

```dataviewjs
const allByXP = dv.pages('"daily"')
  .where(p => p.xp != null)
  .sort(p => p.file.day || p.date, "asc")
  .array();
const pages14 = allByXP.slice(-14);

if (pages14.length === 0) {{
  dv.paragraph("_No data_");
}} else {{

function parseDate(p) {{
  if (p.file && p.file.day) return p.file.day.toFormat("dd.MM");
  const raw = String(p.date||"");
  const parts = raw.split(/[-]/);
  if (parts.length >= 3) return `${{parts[2].padStart(2,"0")}}.${{parts[1].padStart(2,"0")}}`;
  return "—";
}}

const totalXP14 = pages14.reduce((s,p) => s+(Number(p.xp)||0), 0);
const avgXP14   = Math.round(totalXP14 / pages14.length);

const last7 = pages14.slice(-7);
const prev7 = pages14.slice(0, Math.max(pages14.length-7, 0));
const last7Sum = last7.reduce((s,p) => s+(Number(p.xp)||0), 0);
const prev7Sum = prev7.reduce((s,p) => s+(Number(p.xp)||0), 0);
const deltaPct = prev7Sum > 0
  ? Math.round(((last7Sum - prev7Sum) / prev7Sum) * 100)
  : (last7Sum > 0 ? 100 : 0);
const deltaSign = deltaPct >= 0 ? "+" : "";
const deltaClr  = deltaPct >= 0 ? "#a6e3a1" : "#f38ba8";
const deltaBg   = deltaPct >= 0 ? "rgba(166,227,161,0.15)" : "rgba(243,139,168,0.15)";

const xpVals = pages14.map(p => Number(p.xp)||0);
const maxXPVal = Math.max(...xpVals, 1);
const peakIdx  = xpVals.indexOf(maxXPVal);

// Топ-языки за 14 дней (по вкладу XP дня в его топ-язык)
const langTotals = {{}};
for (const p of pages14) {{
  const lang = String(p.top_lang || "Other");
  langTotals[lang] = (langTotals[lang] || 0) + (Number(p.xp) || 0);
}}
const topLangs = Object.entries(langTotals).sort((a,b) => b[1]-a[1]).slice(0,4).map(([l]) => l);

// Текущий уровень (по всей истории) для нижней мини-карточки
const allXPPages = dv.pages('"daily"').where(p => p.xp != null).array();
const totalXPAll = allXPPages.reduce((s,p) => s+(Number(p.xp)||0), 0);
const level      = Math.floor(totalXPAll / 100);
const xpInLevel  = totalXPAll % 100;

// Геометрия графика
const width = 620, height = 230;
const padX = 34, baseline = 190;
const n = pages14.length;
const gap = 6;
const barW = (width - padX*2 - gap*(n-1)) / n;
const barMinH = 14, barMaxH = 168;
const lineTop = 40, lineBottom = 168;

function bx(i) {{ return padX + i*(barW+gap); }}
function barHeight(v) {{ return barMinH + (maxXPVal > 0 ? v/maxXPVal : 0) * (barMaxH - barMinH); }}
function lineY(v) {{ return lineBottom - (v/maxXPVal)*(lineBottom-lineTop); }}

let svgInner = `
<defs>
  <pattern id="hatchDark" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="7" height="7" fill="#22222c"/>
    <line x1="0" y1="0" x2="0" y2="7" stroke="#2c2c38" stroke-width="3"/>
  </pattern>
  <pattern id="hatchPurple" width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <rect width="7" height="7" fill="#7F77DD"/>
    <line x1="0" y1="0" x2="0" y2="7" stroke="#a79cf5" stroke-width="2.5"/>
  </pattern>
  <filter id="peakGlow" x="-60%" y="-60%" width="220%" height="220%">
    <feGaussianBlur stdDeviation="6" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="#7F77DD"/>
    <stop offset="100%" stop-color="#cba6f7"/>
  </linearGradient>
</defs>`;

// Капсулы-бары — высота каждой колонки зависит от активности дня
pages14.forEach((p, i) => {{
  const isPeak = i === peakIdx;
  const h = barHeight(xpVals[i]);
  const x = bx(i);
  const y = baseline - h;
  const fill = isPeak ? "url(#hatchPurple)" : "url(#hatchDark)";
  svgInner += `<rect x="${{x}}" y="${{y}}" width="${{barW}}" height="${{h}}" rx="${{barW/2}}"
    fill="${{fill}}" opacity="${{isPeak?0.95:0.7}}" ${{isPeak?'filter="url(#peakGlow)"':''}}/>`;
}});

// Линия тренда поверх баров
let lineD = "";
pages14.forEach((p, i) => {{
  const x = bx(i) + barW/2;
  const y = lineY(xpVals[i]);
  lineD += (i === 0 ? `M ${{x}} ${{y}}` : ` L ${{x}} ${{y}}`);
}});
svgInner += `<path d="${{lineD}}" fill="none" stroke="url(#lineGrad)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" opacity="0.9"/>`;

// Узлы линии
pages14.forEach((p, i) => {{
  const x = bx(i) + barW/2;
  const y = lineY(xpVals[i]);
  if (i === peakIdx) {{
    svgInner += `<circle cx="${{x}}" cy="${{y}}" r="8" fill="none" stroke="#ffffff" stroke-width="2"/>`;
    svgInner += `<circle cx="${{x}}" cy="${{y}}" r="3" fill="#ffffff"/>`;
  }} else {{
    svgInner += `<circle cx="${{x}}" cy="${{y}}" r="3.5" fill="#cba6f7"/>`;
  }}
}});

// Подписи дат
pages14.forEach((p, i) => {{
  const x = bx(i) + barW/2;
  svgInner += `<text x="${{x}}" y="${{baseline+18}}" text-anchor="middle" font-size="9" fill="#6c7086" font-family="monospace">${{parseDate(p)}}</text>`;
}});

const svgHtml = `<svg width="${{width}}" height="${{height}}" viewBox="0 0 ${{width}} ${{height}}">${{svgInner}}</svg>`;

// Языковые чипы
let pillsHtml = "";
if (topLangs.length > 0) {{
  pillsHtml = `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;position:relative">`;
  topLangs.forEach((lang, i) => {{
    const active = i === 0;
    pillsHtml += `<div style="
      padding:8px 16px;border-radius:999px;font-size:13px;font-weight:600;
      background:${{active ? "#7F77DD" : "#1e1e2a"}};
      color:${{active ? "#f4f3ff" : "#8a8a96"}};
      border:1px solid ${{active ? "#7F77DD" : "#2a2a36"}};
    ">${{lang}}</div>`;
  }});
  pillsHtml += `</div>`;
}}

// Сборка карточки
let html = `
<div style="
  position:relative;
  font-family:'SF Mono','Consolas',monospace;
  background:linear-gradient(160deg,#131318 0%,#0a0a0e 100%);
  border:1px solid rgba(255,255,255,0.07);
  border-radius:22px;
  padding:24px 24px 22px;
  margin:12px 0;
  overflow:hidden;
  box-shadow:0 12px 44px rgba(0,0,0,0.4);
">
  <div style="
    position:absolute;top:-60px;right:-40px;width:340px;height:340px;
    background:linear-gradient(135deg, rgba(127,119,221,0.5), rgba(245,163,255,0.35), transparent 70%);
    filter:blur(50px);transform:rotate(20deg);pointer-events:none;
  "></div>

  <div style="position:relative;display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
    <div style="font-size:20px;font-weight:700;color:#e9e9f0;letter-spacing:0.3px">XP Activity</div>
    <div style="
      background:#1a1a20;border:1px solid #2a2a34;border-radius:999px;
      padding:7px 16px;font-size:12px;color:#a8a8b4;display:flex;align-items:center;gap:6px;
    ">14 DAYS <span style="font-size:9px;color:#6c6c78">▾</span></div>
  </div>

  <div style="position:relative;display:flex;align-items:baseline;gap:14px;margin-bottom:18px;flex-wrap:wrap">
    <span style="
      font-size:52px;font-weight:800;letter-spacing:-1.5px;line-height:1;
      background:linear-gradient(180deg,#ffffff 0%,#9a9aa8 100%);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    ">${{totalXP14}}</span>
    <span style="
      background:${{deltaBg}};color:${{deltaClr}};font-weight:700;font-size:13px;
      padding:4px 10px;border-radius:999px;
    ">${{deltaSign}}${{deltaPct}}%</span>
    <span style="font-size:14px;color:#7a7a86">total XP · last 14 days</span>
  </div>

  ${{pillsHtml}}

  <div style="position:relative;height:1px;background:rgba(255,255,255,0.08);margin-bottom:6px"></div>

  <div style="position:relative">${{svgHtml}}</div>

  <div style="
    position:relative;margin-top:16px;background:rgba(255,255,255,0.03);
    border:1px solid rgba(255,255,255,0.07);border-radius:16px;padding:16px 18px;
  ">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px">
      <div style="display:flex;align-items:baseline;gap:8px">
        <span style="font-size:13px;color:#9a9aa6;font-weight:600">Level</span>
        <span style="font-size:24px;font-weight:800;color:#f2f2f6">${{level}}</span>
      </div>
      <span style="background:rgba(166,227,161,0.15);color:#a6e3a1;font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px">+${{avgXP14}} XP avg/day</span>
    </div>
    <div style="font-size:12px;color:#6c6c78;margin-bottom:10px">${{xpInLevel}} XP now · ${{100-xpInLevel}} XP to level ${{level+1}}</div>
    <div style="background:#1e1e26;border-radius:999px;height:10px;overflow:hidden">
      <div style="width:${{xpInLevel}}%;height:100%;border-radius:999px;background:linear-gradient(90deg,#7F77DD,#cba6f7);box-shadow:0 0 12px rgba(127,119,221,0.5)"></div>
    </div>
  </div>
</div>`;

const container = dv.el("div","");
container.innerHTML = html;
}}
```

---

## Daily Notes

<!-- What I learned, what was hard, what I understood -->
"""
    return note

# ─── ПРОВЕРКА НАСТРОЕК ────────────────────────────────────────────────────────

def check_config():
    """Останавливает скрипт с понятным сообщением, если настройки не заполнены."""
    missing = []
    if not WAKATIME_API_KEY:
        missing.append("WAKATIME_API_KEY — получить на https://wakatime.com/settings/api-key")
    if not VAULT_PATH:
        missing.append("VAULT_PATH — абсолютный путь до вашего Obsidian vault")

    if missing:
        print("⚠️  Скрипт не настроен. Откройте wakatime_to_obsidian.py и заполните:")
        for item in missing:
            print(f"   • {item}")
        sys.exit(1)

    if not Path(VAULT_PATH).exists():
        print(f"⚠️  Указанный VAULT_PATH не найден: {VAULT_PATH}")
        print("   Проверьте, что путь указан правильно и vault существует.")
        sys.exit(1)

# ─── СОЗДАНИЕ ФАЙЛА ──────────────────────────────────────────────────────────

def create_daily_note(target_date: date = None):
    check_config()
    today = target_date or date.today()
    vault = Path(VAULT_PATH)
    daily_path = vault / DAILY_FOLDER
    daily_path.mkdir(parents=True, exist_ok=True)

    note_path = daily_path / f"{today.strftime(DATE_FORMAT)}.md"

    print(f"📡 Загружаю данные WakaTime за {today}...")
    summary = get_wakatime_summary(today)
    parsed = parse_summary(summary)

    print(f"⏱  Кодинг сегодня: {parsed['total_hours']}h (топ-язык: {parsed['top_lang']} {parsed['top_lang_hours']}h)")

    print("📂 Загружаю историю...")
    history = load_all_daily_notes(vault, DAILY_FOLDER)
    # Убираем сегодняшний день из истории (если уже есть)
    history = [h for h in history if h["date"] != today]

    streak = calculate_streak(history, today, parsed["total_hours"])
    best_streak = max(get_best_streak(history), streak)
    total_xp = get_total_xp(history)  # XP за всю историю ДО сегодняшнего дня
    xp_today = calculate_xp(
        parsed["top_lang_hours"], parsed["other_hours"], streak,
        parsed["total_hours"], total_xp,
    )
    weekly = get_weekly_stats(history, today)
    history_top_lang = get_history_top_lang(history)

    achievement_bonus = get_achievement_xp_bonus(parsed["total_hours"], streak)
    milestone_bonus = get_milestone_xp_bonus(total_xp, total_xp + xp_today)
    if achievement_bonus or milestone_bonus:
        print(f"🏅 Бонус за ачивки: +{achievement_bonus} XP"
              + (f" | Веха: +{milestone_bonus} XP" if milestone_bonus else ""))

    print(f"🔥 Стрик: {streak} дн. | XP сегодня: +{xp_today} | Всего XP: {total_xp + xp_today}")
    print(f"🏆 Топ-язык истории: {history_top_lang}")

    note_content = render_note(
        today, parsed, streak, best_streak,
        xp_today, total_xp, history, weekly,
        history_top_lang,
    )

    note_path.write_text(note_content, encoding="utf-8")
    print(f"✅ Заметка сохранена: {note_path}")


if __name__ == "__main__":
    create_daily_note()