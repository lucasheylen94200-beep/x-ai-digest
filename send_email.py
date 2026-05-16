#!/usr/bin/env python3
"""Envoie le digest du jour par email via Resend.

Usage :
  python send_email.py                 # envoie le digest du jour
  python send_email.py 2026-05-15      # envoie le digest d'une date specifique
  python send_email.py --dry-run       # construit l'email sans envoyer (debug)
"""

import json
import os
import sys
import re
import html as html_lib
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"

# Lien de la page hostee (sera renseigne apres setup GitHub Pages)
HOSTED_URL = os.environ.get("DIGEST_PUBLIC_URL", "")

# Destinataire (free tier Resend : doit etre le meme que l'email du compte Resend)
TO_EMAIL = os.environ.get("DIGEST_TO_EMAIL", "lucas.heylen94200@gmail.com")
FROM_EMAIL = "Daily AI Digest <onboarding@resend.dev>"


def esc(s):
    return html_lib.escape(str(s) if s else "")


def fmt_date_fr(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        days = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
        months = ["janvier","fevrier","mars","avril","mai","juin","juillet","aout","septembre","octobre","novembre","decembre"]
        return f"{days[d.weekday()]} {d.day} {months[d.month-1]}"
    except Exception:
        return date_str


def render_tweet_email(t, is_highlight=False):
    """Rendu HTML compact d'un tweet pour email."""
    text_fr = esc(t.get("text_fr") or t.get("text") or "")
    handle = (t.get("handle") or "").lstrip("@")
    name = esc(t.get("author_name") or "")
    link = esc(t.get("link") or "")
    decryptage = esc(t.get("decryptage") or "")
    highlight_reason = esc(t.get("highlight_reason") or "")

    style = ("background:#fff5f5;border-left:4px solid #ff6b35;"
             if is_highlight
             else "background:white;border:1px solid #e5e5e7;")

    html = f'<div style="{style}border-radius:10px;padding:14px 16px;margin:10px 0;">'

    if is_highlight and highlight_reason:
        html += f'<div style="color:#cc4400;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px;">&#9733; {highlight_reason}</div>'

    html += f'<div style="margin-bottom:4px;"><strong style="color:#1d1d1f;">{name}</strong> <span style="color:#6e6e73;font-size:13px;">@{esc(handle)}</span></div>'
    html += f'<div style="color:#1d1d1f;font-size:14px;line-height:1.5;">{text_fr}</div>'

    if decryptage:
        html += f'<div style="background:#eef6ff;border-left:3px solid #0071e3;padding:8px 11px;border-radius:6px;margin-top:8px;font-size:13px;color:#1d3a5c;"><strong style="color:#0071e3;font-size:11px;">EN CLAIR :</strong> {decryptage}</div>'

    if link:
        html += f'<a href="{link}" style="display:inline-block;margin-top:8px;color:#0071e3;font-size:13px;text-decoration:none;">Voir sur X &rarr;</a>'

    html += '</div>'
    return html


def build_email_html(data):
    """Construit le contenu HTML de l'email a partir du JSON du jour."""
    p = data.get("processed") or {}
    date_str = data.get("date", "")
    summary = p.get("summary") or ""
    highlights = p.get("highlights") or []
    glossaire = p.get("glossaire") or []
    by_cat = p.get("by_category") or {}
    cat_summaries = p.get("category_summaries") or {}

    # Compteurs par categorie
    cat_meta = {
        "actu":   {"emoji": "&#128240;", "label": "Actualite"},
        "tips":   {"emoji": "&#128161;", "label": "Tips"},
        "idees":  {"emoji": "&#129504;", "label": "Idees"},
        "outils": {"emoji": "&#128736;", "label": "Outils"},
    }

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily AI Digest</title>
</head>
<body style="margin:0;padding:0;background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1d1d1f;">
<div style="max-width:680px;margin:0 auto;padding:24px 20px;">

  <!-- Header -->
  <h1 style="margin:0 0 4px;font-size:24px;color:#1d1d1f;">Daily AI Digest</h1>
  <p style="margin:0 0 24px;color:#6e6e73;font-size:14px;">{esc(fmt_date_fr(date_str))} &middot; Ce que disent les 41 plus gros profils IA sur X</p>
"""

    # Bouton vers page complete
    if HOSTED_URL:
        html += f"""
  <a href="{esc(HOSTED_URL)}" style="display:inline-block;background:#0071e3;color:white;padding:12px 24px;text-decoration:none;border-radius:10px;font-weight:600;font-size:15px;margin-bottom:24px;">Voir la page complete (interactive) &rarr;</a>
"""

    # Resume du jour
    if summary:
        html += f"""
  <div style="background:linear-gradient(135deg,#fff8e1,#fff3c4);padding:16px 18px;border-radius:12px;border-left:4px solid #f4b400;margin-bottom:24px;">
    <div style="text-transform:uppercase;letter-spacing:.06em;font-size:11px;color:#9a7700;font-weight:700;margin-bottom:6px;">Resume du jour</div>
    <div style="color:#1d1d1f;font-size:14px;line-height:1.55;">{esc(summary)}</div>
  </div>
"""

    # Highlights
    if highlights:
        html += '<h2 style="font-size:18px;color:#1d1d1f;margin:24px 0 12px;">A ne pas manquer</h2>'
        for t in highlights:
            html += render_tweet_email(t, is_highlight=True)

    # Categories cards avec leur summary
    html += '<h2 style="font-size:18px;color:#1d1d1f;margin:24px 0 12px;">Resumes par categorie</h2>'
    for key, meta in cat_meta.items():
        cat_sum = cat_summaries.get(key, "")
        count = len(by_cat.get(key) or [])
        if not cat_sum and count == 0:
            continue
        html += f"""
  <div style="background:white;border:1px solid #e5e5e7;border-left:4px solid #0071e3;border-radius:10px;padding:12px 16px;margin:10px 0;">
    <div style="font-weight:700;color:#1d1d1f;margin-bottom:4px;">{meta['emoji']} {meta['label']} <span style="color:#6e6e73;font-weight:400;font-size:13px;">&middot; {count} publication{'s' if count > 1 else ''}</span></div>
    <div style="color:#1d1d1f;font-size:13px;line-height:1.5;">{esc(cat_sum) if cat_sum else '<em style="color:#999;">Pas de resume disponible</em>'}</div>
  </div>
"""

    # Glossaire
    if glossaire:
        html += '<h2 style="font-size:18px;color:#1d1d1f;margin:24px 0 12px;">Glossaire du jour</h2>'
        html += '<div style="background:#f0f4ff;border:1px solid #d0dcf0;border-radius:12px;padding:14px 18px;">'
        for g in glossaire:
            html += f'<div style="margin-bottom:10px;"><strong style="color:#0050b3;">{esc(g.get("terme",""))}</strong><br><span style="color:#1d1d1f;font-size:13px;">{esc(g.get("definition",""))}</span></div>'
        html += '</div>'

    # CTA en bas
    if HOSTED_URL:
        html += f"""
  <div style="text-align:center;margin:32px 0 16px;">
    <a href="{esc(HOSTED_URL)}" style="display:inline-block;background:#0071e3;color:white;padding:12px 28px;text-decoration:none;border-radius:10px;font-weight:600;font-size:15px;">Acceder a la page complete</a>
    <div style="color:#6e6e73;font-size:12px;margin-top:8px;">Tu y trouveras les {sum(len(v or []) for v in by_cat.values())} publications du jour, classees par categorie</div>
  </div>
"""

    # Footer
    html += """
  <div style="border-top:1px solid #e5e5e7;margin-top:24px;padding-top:14px;color:#6e6e73;font-size:12px;text-align:center;">
    Genere automatiquement &middot; <a href="#" style="color:#6e6e73;">Daily AI Digest</a>
  </div>
</div>
</body></html>"""

    return html


def send_via_resend(subject, html_body, to_email):
    """Envoie l'email via l'API Resend."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("ERREUR: RESEND_API_KEY non definie")
        return False

    payload = {
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DailyAIDigest/1.0 (+https://github.com/lucasheylen94200-bip/x-ai-digest)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            print(f"[email] envoye - id Resend : {result.get('id')}")
            # Pose un flag pour permettre au watchdog de detecter qu'on a envoye aujourd'hui
            today_flag = BASE / f".email_sent_{datetime.now().strftime('%Y-%m-%d')}.flag"
            today_flag.write_text(datetime.now().isoformat(timespec="seconds"))
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[email] erreur HTTP {e.code} : {err_body}")
        return False
    except Exception as e:
        print(f"[email] erreur : {e}")
        return False


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    date_arg = next((a for a in args if not a.startswith("--")), None)

    if date_arg:
        day_file = DATA_DIR / f"{date_arg}.json"
    else:
        # Cherche le fichier le plus recent
        files = sorted(DATA_DIR.glob("[0-9]*.json"))
        if not files:
            print("ERREUR: aucun fichier dans data/")
            return 1
        day_file = files[-1]

    if not day_file.exists():
        print(f"ERREUR: {day_file} introuvable")
        return 1

    data = json.loads(day_file.read_text(encoding="utf-8"))
    html_body = build_email_html(data)
    date_str = data.get("date", "")
    subject = f"AI Digest - {fmt_date_fr(date_str)}"

    print(f"[email] sujet : {subject}")
    print(f"[email] destinataire : {TO_EMAIL}")
    print(f"[email] taille HTML : {len(html_body)} chars")

    if dry_run:
        out_file = BASE / "email_preview.html"
        out_file.write_text(html_body, encoding="utf-8")
        print(f"[email] dry-run : preview sauvee dans {out_file}")
        return 0

    ok = send_via_resend(subject, html_body, TO_EMAIL)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
