#!/usr/bin/env python3
"""Watchdog - surveille le pipeline Daily AI Digest et tente de l'auto-reparer.

Lance par Windows Task Scheduler toutes les 4h entre 7h et 23h.

Usage :
  python watchdog.py            # cycle complet check + auto-fix
  python watchdog.py --check    # juste les checks, sans auto-fix
"""

import json
import os
import sys
import shutil
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
HEALTH_DIR = BASE / "health"
HEALTH_DIR.mkdir(exist_ok=True)
HEALTH_FILE = HEALTH_DIR / "health.json"
ALERT_FLAG = BASE / ".alert_sent.flag"

DIGEST_PUBLIC_URL = os.environ.get("DIGEST_PUBLIC_URL", "")
TO_EMAIL = os.environ.get("DIGEST_TO_EMAIL", "lucas.heylen94200@gmail.com")


def load_history():
    if HEALTH_FILE.exists():
        try:
            return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"runs": []}


def save_history(history):
    # Garde uniquement les 30 derniers jours
    cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    history["runs"] = [r for r in history["runs"] if r["timestamp"] >= cutoff]
    HEALTH_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================================
# HEALTH CHECKS - chaque fonction renvoie {"ok": bool, "details": str}
# ============================================================================

def check_today_data_exists():
    today = datetime.now().strftime("%Y-%m-%d")
    f = DATA_DIR / f"{today}.json"
    if f.exists():
        return {"ok": True, "details": f"{f.name} ({f.stat().st_size // 1024} Ko)"}
    return {"ok": False, "details": f"manquant : data/{today}.json"}


def check_translation_rate():
    today = datetime.now().strftime("%Y-%m-%d")
    f = DATA_DIR / f"{today}.json"
    if not f.exists():
        return {"ok": False, "details": "pas de fichier du jour"}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "details": f"JSON cassee : {e}"}
    v = d.get("validation") or {}
    pct = v.get("translated_pct", 0)
    total = v.get("total", 0)
    return {"ok": pct >= 80 and total >= 20, "details": f"{pct}% sur {total} tweets"}


def check_glossary_present():
    today = datetime.now().strftime("%Y-%m-%d")
    f = DATA_DIR / f"{today}.json"
    if not f.exists():
        return {"ok": False, "details": "pas de fichier du jour"}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "details": "JSON cassee"}
    g = (d.get("processed") or {}).get("glossaire") or []
    return {"ok": len(g) >= 3, "details": f"{len(g)} termes"}


def check_email_sent_today():
    today = datetime.now().strftime("%Y-%m-%d")
    flag = BASE / f".email_sent_{today}.flag"
    return {"ok": flag.exists(), "details": "ok" if flag.exists() else "non envoye"}


def check_github_pages_up():
    if not DIGEST_PUBLIC_URL:
        return {"ok": False, "details": "DIGEST_PUBLIC_URL absente"}
    try:
        req = urllib.request.Request(DIGEST_PUBLIC_URL, headers={"User-Agent": "DAID-Watchdog/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"ok": r.status == 200, "details": f"HTTP {r.status}"}
    except urllib.error.HTTPError as e:
        return {"ok": False, "details": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "details": str(e)[:120]}


def check_last_commit_recent():
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cI"],
            cwd=str(BASE), text=True, timeout=10,
        ).strip()
        commit_date = datetime.fromisoformat(out)
        now = datetime.now(commit_date.tzinfo)
        age_h = (now - commit_date).total_seconds() / 3600
        return {"ok": age_h < 36, "details": f"il y a {age_h:.1f}h"}
    except Exception as e:
        return {"ok": False, "details": str(e)[:120]}


def check_env_vars():
    required = ["GEMINI_API_KEY", "RESEND_API_KEY", "GITHUB_TOKEN", "DIGEST_PUBLIC_URL"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        return {"ok": False, "details": f"manque : {', '.join(missing)}"}
    return {"ok": True, "details": "4/4 presentes"}


def check_disk_space():
    try:
        free_gb = shutil.disk_usage(str(BASE)).free / (1024 ** 3)
        return {"ok": free_gb > 1.0, "details": f"{free_gb:.1f} Go libre"}
    except Exception as e:
        return {"ok": False, "details": str(e)[:120]}


# ============================================================================
# AUTO-FIXES - chaque fonction renvoie True si reussi, False sinon
# ============================================================================

def run_subprocess(args, timeout):
    try:
        result = subprocess.run(args, cwd=str(BASE), capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0
    except Exception:
        return False


def fix_run_pipeline_full():
    return run_subprocess([sys.executable, str(BASE / "digest.py"), "all"], timeout=600)


def fix_rerun_process_only():
    ok = run_subprocess([sys.executable, str(BASE / "digest.py"), "process"], timeout=400)
    if ok:
        run_subprocess([sys.executable, str(BASE / "digest.py"), "build"], timeout=60)
    return ok


def fix_resend_email():
    return run_subprocess([sys.executable, str(BASE / "send_email.py")], timeout=60)


def fix_force_rebuild_pages():
    try:
        subprocess.run(["git", "add", "-A"], cwd=str(BASE), timeout=20)
        subprocess.run(["git", "commit", "-m", "watchdog: rebuild pages", "--allow-empty"], cwd=str(BASE), timeout=20)
        result = subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE), timeout=60)
        return result.returncode == 0
    except Exception:
        return False


# ============================================================================
# ALERT MAIL
# ============================================================================

def send_alert_email(reason, results):
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key or not TO_EMAIL:
        return False
    failed = [(name, info) for name, info in results.items() if not info.get("ok")]
    rows = "".join([
        f'<tr><td style="padding:6px 12px;border-bottom:1px solid #eee;"><strong>{name}</strong></td>'
        f'<td style="padding:6px 12px;border-bottom:1px solid #eee;color:#c00;">{info.get("details","")}</td></tr>'
        for name, info in failed
    ])
    html = (
        '<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"></head>'
        '<body style="font-family:-apple-system,Segoe UI,sans-serif;color:#1d1d1f;background:#fff5f5;padding:24px;">'
        '<div style="max-width:600px;margin:0 auto;background:white;padding:24px;border-radius:12px;border-top:6px solid #c00;">'
        '<h2 style="color:#c00;margin:0 0 8px;">Alerte Daily AI Digest</h2>'
        '<p>Le watchdog detecte que le pipeline est en panne depuis 24h+.</p>'
        f'<p><strong>Raison :</strong> {reason}</p>'
        f'<table style="width:100%;border-collapse:collapse;margin:16px 0;background:#fafafa;border-radius:8px;">'
        '<thead><tr><th style="text-align:left;padding:8px 12px;background:#f0f0f0;">Check</th>'
        '<th style="text-align:left;padding:8px 12px;background:#f0f0f0;">Detail</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        '<p style="color:#666;font-size:13px;">Cette alerte ne sera pas renvoyee avant 24h.</p>'
        '<p>Action conseillee : ouvre <a href="' + DIGEST_PUBLIC_URL + '">la page</a> et regarde le panneau Statut.</p>'
        '</div></body></html>'
    )
    payload = json.dumps({
        "from": "Daily AI Digest <onboarding@resend.dev>",
        "to": [TO_EMAIL],
        "subject": "[ALERTE] Daily AI Digest en panne depuis 24h+",
        "html": html,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DailyAIDigest-Watchdog/1.0",
        }, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"[alert] echec envoi mail : {e}")
        return False


# ============================================================================
# ORCHESTRATION
# ============================================================================

CHECKS_AND_FIXES = [
    # nom,                  fonction_check,             fonction_fix (None si humain requis)
    ("today_data_exists",   check_today_data_exists,    fix_run_pipeline_full),
    ("translation_rate",    check_translation_rate,     fix_rerun_process_only),
    ("glossary_present",    check_glossary_present,     fix_rerun_process_only),
    ("github_pages_up",     check_github_pages_up,      fix_force_rebuild_pages),
    ("last_commit_recent",  check_last_commit_recent,   fix_run_pipeline_full),
    ("email_sent_today",    check_email_sent_today,     fix_resend_email),
    ("env_vars",            check_env_vars,             None),  # humain requis
    ("disk_space",          check_disk_space,           None),  # humain requis
]


def run_watchdog(auto_fix=True):
    print(f"\n=== Watchdog {datetime.now().isoformat(timespec='seconds')} ===")
    history = load_history()

    results = {}
    fixes_applied = []

    for name, check_fn, fix_fn in CHECKS_AND_FIXES:
        try:
            result = check_fn()
        except Exception as e:
            result = {"ok": False, "details": f"exception : {e}"}
        results[name] = result
        status_icon = "OK" if result["ok"] else "KO"
        print(f"  [{status_icon}] {name:25s} : {result['details']}")

        if not result["ok"] and fix_fn and auto_fix:
            print(f"        -> tentative auto-fix...")
            try:
                fixed = fix_fn()
                fixes_applied.append({"check": name, "fix": fix_fn.__name__, "success": fixed})
                if fixed:
                    print(f"        OK auto-fix reussi")
                    # Re-check pour mettre a jour le statut
                    try:
                        new_result = check_fn()
                        results[name] = {**new_result, "auto_fixed": True}
                    except Exception:
                        pass
                else:
                    print(f"        KO auto-fix echoue")
            except Exception as e:
                print(f"        KO exception auto-fix : {e}")
                fixes_applied.append({"check": name, "fix": fix_fn.__name__, "success": False, "error": str(e)[:200]})

    all_ok = all(r["ok"] for r in results.values())

    run_record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "all_ok": all_ok,
        "checks": results,
        "fixes_applied": fixes_applied,
    }
    history["runs"].append(run_record)
    save_history(history)

    # Verification 24h+ sans succes
    if not all_ok:
        last_success = None
        for r in reversed(history["runs"][:-1]):  # exclure le run courant
            if r.get("all_ok"):
                last_success = datetime.fromisoformat(r["timestamp"])
                break
        # Pour eviter de spammer au demarrage : on n'alerte QUE si on a deja eu au moins 1 succes,
        # et que ce dernier succes date de plus de 24h.
        critical = last_success is not None and (datetime.now() - last_success) > timedelta(hours=24)
        if critical:
            should_send = True
            if ALERT_FLAG.exists():
                try:
                    last_alert = datetime.fromisoformat(ALERT_FLAG.read_text().strip())
                    if datetime.now() - last_alert < timedelta(hours=24):
                        should_send = False
                except Exception:
                    pass
            if should_send:
                print("\n=> Envoi mail d'alerte (panne 24h+)")
                failed_names = [n for n, r in results.items() if not r["ok"]]
                if send_alert_email(reason=f"Echec de {len(failed_names)} checks", results=results):
                    ALERT_FLAG.write_text(datetime.now().isoformat(timespec="seconds"))
                    print("=> Mail d'alerte envoye")

    print(f"\n=> Resultat : {'TOUT OK' if all_ok else 'PROBLEMES DETECTES'} ({len(fixes_applied)} fixes tentes)")
    return 0 if all_ok else 1


def main():
    auto_fix = "--check" not in sys.argv
    sys.exit(run_watchdog(auto_fix=auto_fix))


if __name__ == "__main__":
    main()
