#!/usr/bin/env python3
"""Daily X (Twitter) AI digest — version gratuite.

Usage :
  python digest.py             # fetch + traduction/synthèse + build HTML
  python digest.py fetch       # juste récupérer les tweets
  python digest.py process     # juste traduire/synthétiser (nécessite GEMINI_API_KEY)
  python digest.py build       # juste regénérer index.html à partir des données
"""

import json
import os
import sys
import re
import html as html_lib
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)
ACCOUNTS_FILE = BASE / "accounts.json"
HTML_OUT = BASE / "index.html"

NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.net",
    "https://nitter.unixfox.eu",
    "https://nitter.fdn.fr",
    "https://nitter.cz",
    "https://nitter.kavin.rocks",
    "https://nitter.1d4.us",
    "https://nitter.moomoo.me",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_user_tweets(handle, max_items=5):
    """Essaie plusieurs instances Nitter jusqu'a en trouver une qui marche."""
    for instance in NITTER_INSTANCES:
        url = f"{instance}/{handle}/rss"
        xml = http_get(url)
        if not xml or "<rss" not in xml:
            continue
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            continue
        items = []
        for item in list(root.iter("item"))[:max_items]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()
            text = re.sub(r"<[^>]+>", " ", desc or title)
            text = html_lib.unescape(text).strip()
            text = re.sub(r"\s+", " ", text)
            if not text:
                continue
            items.append({
                "handle": handle,
                "text": text,
                "link": link,
                "published": pub,
            })
        if items:
            return items, instance
    return [], None


def load_accounts():
    return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))["accounts"]


def fetch_all():
    accounts = load_accounts()
    today = datetime.now().strftime("%Y-%m-%d")
    all_tweets = []
    failed = []
    for acc in accounts:
        print(f"  @{acc['handle']:<20}", end=" ", flush=True)
        items, instance = fetch_user_tweets(acc["handle"], max_items=5)
        if items:
            for item in items:
                item["author_name"] = acc["name"]
                item["category_hint"] = acc.get("category", "misc")
                item["source_lang"] = acc.get("lang", "en")
            all_tweets.extend(items)
            print(f"-> {len(items)} tweets ({instance})")
        else:
            failed.append(acc["handle"])
            print("-> ECHEC")
        time.sleep(0.5)

    day_file = DATA_DIR / f"{today}.json"
    existing = {}
    if day_file.exists():
        existing = json.loads(day_file.read_text(encoding="utf-8"))
    payload = {
        "date": today,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "tweets": all_tweets,
        "failed_accounts": failed,
        "processed": existing.get("processed"),
    }
    day_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[fetch] {len(all_tweets)} tweets recuperes, {len(failed)} comptes en echec")
    print(f"[fetch] {day_file}")
    return day_file


def process_with_gemini(day_file):
    """Traduit + synthetise via Gemini free tier."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[process] GEMINI_API_KEY non definie. Etapes :")
        print("  1. https://aistudio.google.com/apikey (cle gratuite, sans CB)")
        print("  2. setx GEMINI_API_KEY \"ta_cle\"")
        print("  3. Relancer un nouveau terminal")
        return False
    try:
        from google import genai
    except ImportError:
        print("[process] google-genai non installe. Lancer : pip install google-genai")
        return False

    data = json.loads(day_file.read_text(encoding="utf-8"))
    tweets = data.get("tweets") or []
    if not tweets:
        print("[process] aucun tweet a traiter")
        return False

    tweets_block = "\n\n".join([
        f"#{i}. [{t['author_name']} @{t['handle']}] (lang={t['source_lang']})\n"
        f"   Texte: {t['text']}\n"
        f"   Lien: {t['link']}"
        for i, t in enumerate(tweets)
    ])

    prompt = f"""Tu es un curateur pedagogue qui ecrit pour un DEBUTANT francophone passionne par l'IA.
Ton lecteur ne connait pas le jargon technique : explique-lui ce qui compte sans le noyer.
Tu DOIS produire du francais natif et naturel, jamais du copie-colle de l'anglais.

Voici les tweets recuperes aujourd'hui des plus grands devs/chercheurs/createurs IA :

{tweets_block}

=== TACHES (toutes obligatoires) ===

1. TRADUCTION OBLIGATOIRE EN FRANCAIS :
   - Le champ "text_fr" DOIT TOUJOURS contenir le texte EN FRANCAIS.
   - Si le tweet est deja en francais : recopie tel quel, et mets "text_original": null
   - Si le tweet est en anglais : TRADUIS-LE en francais naturel. NE RECOPIE JAMAIS l'anglais dans text_fr.
   - Garde tel quel : code, commandes shell, noms de fonctions/variables, URLs, @mentions, #hashtags.
   - Si tu doutes : traduis. Mieux vaut traduire un tweet francais que de laisser de l'anglais.
   - REGLE ABSOLUE : text_fr != text_original. Si text_fr et text_original sont identiques, c'est un bug.

2. CLASSIFICATION (chaque tweet dans UNE SEULE categorie) :
   - "actu" : annonces, lancements officiels, news factuelles
   - "tips" : conseils pratiques, snippets de code, retours d'experience applicables
   - "idees" : reflexions, opinions, debats, prospective
   - "outils" : nouveaux produits, demos, lancements de modeles ou outils a tester
   - REGLE : un tweet appartient a UNE seule categorie. Choisis la plus pertinente.
   - Elimine les vrais doublons (meme info tweetee par plusieurs -> garde la version la plus claire).

3. DECRYPTAGE PEDAGOGIQUE :
   - Pour CHAQUE tweet contenant du jargon ou une reference inconnue du grand public, ajoute "decryptage" : UNE phrase francaise simple qui vulgarise.
   - Si le tweet est deja accessible, mets "decryptage": null.

4. RESUME GLOBAL DU JOUR ("summary") :
   - 3-4 phrases EN FRANCAIS, oriente apprentissage : que doit retenir un debutant aujourd'hui ?

5. RESUMES PAR CATEGORIE ("category_summaries") :
   - Pour CHACUNE des 4 categories, ecris 2-3 phrases EN FRANCAIS qui synthetisent les principaux themes/outils/idees abordes ce jour-la dans cette categorie.
   - Ces resumes doivent etre DIFFERENTS du summary global : ils sont specifiques a leur categorie.
   - Format : {{"actu": "...", "tips": "...", "idees": "...", "outils": "..."}}

6. HIGHLIGHTS "A ne pas manquer" :
   - Selectionne 3 a 4 tweets COUP DE COEUR : les plus importants/utiles/instructifs du jour.
   - Pour chacun, ajoute "highlight_reason" (1 phrase : pourquoi tu l'as selectionne) et "category" (sa categorie d'origine).
   - Les highlights peuvent etre des duplicatas de tweets dans by_category (c'est volontaire).

7. GLOSSAIRE :
   - 4 a 7 termes techniques rencontres aujourd'hui, avec definition courte (1 phrase) en francais simple.

=== STRUCTURE DE SORTIE (JSON valide, rien d'autre) ===

IMPORTANT : ecris les champs DANS CET ORDRE EXACT (le glossaire et les resumes courts en premier pour qu'ils soient toujours sauves meme si la sortie est tronquee).

{{
  "summary": "...",
  "glossaire": [
    {{"terme": "...", "definition": "..."}},
    ...
  ],
  "category_summaries": {{
    "actu":   "...",
    "tips":   "...",
    "idees":  "...",
    "outils": "..."
  }},
  "highlights": [
    {{"author_name":"...","handle":"...","text_fr":"...","text_original":"...","link":"...","decryptage":"...","category":"tips","highlight_reason":"..."}},
    ...
  ],
  "by_category": {{
    "actu":   [{{"author_name":"...","handle":"...","text_fr":"...","text_original":"...","link":"...","decryptage":"..."}}],
    "tips":   [...],
    "idees":  [...],
    "outils": [...]
  }}
}}

RAPPEL FINAL : text_fr en FRANCAIS toujours. text_original = anglais source (ou null si deja FR). text_fr != text_original."""

    from google.genai import types
    client = genai.Client(api_key=api_key)
    # On force la sortie JSON structuree (evite les guillemets mal echappes)
    # et on autorise une sortie longue (sinon Gemini tronque a 8192 tokens par defaut, ce qui casse le JSON)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        max_output_tokens=65536,
    )
    # Modeles vivants en 2026 (les 1.5-* ont ete retires)
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-flash-latest",
    ]
    response = call_gemini_with_retry(client, models_to_try, prompt, config)
    if response is None:
        print(f"[process] tous les modeles ont echoue.")
        return False

    text = (response.text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)

    try:
        processed = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[process] JSON cassee ({e}), tentative de reparation...")
        try:
            from json_repair import repair_json
            repaired = repair_json(text)
            processed = json.loads(repaired)
            print("[process] reparation reussie")
        except Exception as e2:
            print(f"[process] reparation echouee : {e2}")
            print(f"--- debut reponse ---\n{text[:800]}\n--- fin ---")
            return False

    # Verification d'integrite : si la sortie est trop pauvre, on ne sauve pas (probable troncature)
    by_cat = processed.get("by_category") or {}
    total_processed = sum(len(v or []) for v in by_cat.values())
    n_tweets_in = len(tweets)
    if total_processed < max(5, n_tweets_in * 0.2):
        print(f"[process] ANOMALIE : {total_processed} tweets en sortie pour {n_tweets_in} en entree ({100*total_processed/max(1,n_tweets_in):.0f}%).")
        print(f"[process] Probablement reponse Gemini tronquee. On ne sauve pas, le fichier precedent reste valide.")
        return False
    if not processed.get("summary"):
        print("[process] ANOMALIE : pas de summary genere. On ne sauve pas.")
        return False
    if not processed.get("category_summaries"):
        print("[process] AVERTISSEMENT : category_summaries manquant (prompt mal suivi).")

    # Validation + auto-reparation des traductions ratees
    processed = validate_and_repair_translations(processed, client, config)

    # Validation + auto-reparation du glossaire (s'il manque suite a une troncature)
    processed = validate_and_repair_glossaire(processed, client, config)

    data["processed"] = processed
    data["processed_at"] = datetime.now().isoformat(timespec="seconds")
    data["validation"] = validate_data_quality(processed)
    day_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[process] traduit + categorise : {day_file}")
    v = data["validation"]
    print(f"[process] qualite : {v['translated_pct']}% traduits, {v['with_decryptage_pct']}% avec decryptage")
    return True


def call_gemini_with_retry(client, models, prompt, config, max_rounds=3, retry_delay=30):
    """Cascade : essaie chaque modele, retry sur 503 avec delai. Renvoie response ou None."""
    for round_idx in range(max_rounds):
        for model in models:
            try:
                print(f"[process] essai modele {model} (round {round_idx+1})...", flush=True)
                response = client.models.generate_content(model=model, contents=prompt, config=config)
                print(f"[process] OK avec {model}", flush=True)
                return response
            except Exception as e:
                msg = str(e)
                short_msg = msg[:160]
                # Detection des erreurs transientes (503) qui meritent un retry
                is_transient = "503" in msg or "UNAVAILABLE" in msg or "Server disconnected" in msg
                # Erreurs permanentes (404, 401, etc) : on ne re-essaie pas ce modele
                is_permanent = "404" in msg or "NOT_FOUND" in msg or "401" in msg
                if is_permanent:
                    print(f"[process]   {model} indisponible (permanent), on l'ignore : {short_msg}", flush=True)
                    continue
                print(f"[process]   echec {model} : {short_msg}", flush=True)
        # Apres avoir essaye tous les modeles sans succes : on attend et on recommence
        if round_idx < max_rounds - 1:
            print(f"[process] tous les modeles surcharges, attente {retry_delay}s avant round {round_idx+2}...", flush=True)
            time.sleep(retry_delay)
    return None


def looks_english(s):
    """Heuristique simple : detecte si une chaine est encore en anglais."""
    if not s:
        return False
    en = re.findall(r"\b(the|and|with|that|this|just|will|would|been|have|has|are|was|were|from|about|into)\b", s.lower())
    fr = re.findall(r"\b(le|la|les|un|une|des|et|que|pour|avec|dans|sur|par|mais|cest|aussi|tres|plus|deja|nous|vous|ils|elles|notre|votre|leur)\b", s.lower())
    # Au moins 2 marqueurs EN et moins de 2 marqueurs FR -> probablement encore en anglais
    return len(en) >= 2 and len(fr) < 2


def needs_retranslation(tweet):
    """Un tweet a besoin d'etre retraduit si text_fr = text_original, ou si text_fr est manifestement en anglais."""
    text_fr = tweet.get("text_fr", "") or ""
    text_original = tweet.get("text_original") or ""
    if text_fr and text_original and text_fr.strip() == text_original.strip():
        return True
    if text_fr and not text_original and looks_english(text_fr):
        # text_original null mais text_fr ressemble a de l'anglais -> Gemini a flag a tort "deja FR"
        return True
    return False


def retranslate_tweets(tweets_to_fix, client, config):
    """Renvoie un batch de tweets a Gemini pour traduction stricte. Renvoie un dict {index: text_fr_traduit}."""
    if not tweets_to_fix:
        return {}
    items_block = "\n".join([
        f"#{i}: {t['text']}"
        for i, t in tweets_to_fix
    ])
    retry_prompt = f"""Traduis ces textes anglais en francais naturel. Garde tel quel le code, les commandes, les @mentions, les URLs.
Reponds STRICTEMENT au format JSON : {{"translations": [{{"id": <numero>, "fr": "<traduction francaise>"}}, ...]}}.

{items_block}"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=retry_prompt,
            config=config,
        )
        text = (response.text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            from json_repair import repair_json
            payload = json.loads(repair_json(text))
        out = {}
        for entry in payload.get("translations", []):
            idx = entry.get("id")
            fr = entry.get("fr")
            if isinstance(idx, int) and fr:
                out[idx] = fr
        return out
    except Exception as e:
        print(f"[repair] retraduction echouee : {e}")
        return {}


def validate_and_repair_translations(processed, client, config):
    """Detecte les tweets non traduits et les renvoie en batch a Gemini pour correction."""
    candidates = []  # liste de (chemin, tweet)
    # Parcourir highlights + by_category
    for i, t in enumerate(processed.get("highlights", []) or []):
        if needs_retranslation(t):
            candidates.append((("highlights", i), t))
    by_cat = processed.get("by_category") or {}
    for cat, items in by_cat.items():
        for i, t in enumerate(items):
            if needs_retranslation(t):
                candidates.append((("by_category", cat, i), t))

    if not candidates:
        print("[repair] aucune retraduction necessaire")
        return processed

    print(f"[repair] {len(candidates)} tweets a retraduire...")
    # Preparer batch
    batch = [(idx, {"text": (t.get("text_original") or t.get("text_fr") or "")}) for idx, (_, t) in enumerate(candidates)]
    translations = retranslate_tweets(batch, client, config)

    fixed = 0
    for idx, (path, t) in enumerate(candidates):
        if idx in translations:
            new_fr = translations[idx]
            # Si text_original etait null, on le remplit avec l'ancien text_fr (qui etait en fait l'anglais)
            if not t.get("text_original"):
                t["text_original"] = t.get("text_fr")
            t["text_fr"] = new_fr
            fixed += 1
    print(f"[repair] {fixed}/{len(candidates)} tweets reparees")
    return processed


def validate_and_repair_glossaire(processed, client, config):
    """Si le glossaire est vide/absent, relance Gemini juste pour lui."""
    gloss = processed.get("glossaire") or []
    if gloss and len(gloss) >= 3:
        return processed  # OK

    print(f"[repair] glossaire manquant ({len(gloss)} termes), regeneration...")
    samples = []
    for items in (processed.get("by_category") or {}).values():
        for t in items[:8]:
            txt = t.get("text_fr") or t.get("text_original") or ""
            if txt:
                samples.append(txt[:200])
    if not samples:
        print("[repair] pas assez de donnees pour generer un glossaire")
        return processed

    sample_block = "\n".join(f"- {s}" for s in samples[:40])
    prompt = f"""Voici des extraits de tweets d'aujourd'hui sur l'IA :

{sample_block}

Extrais 4 a 7 termes techniques qui reviennent dans ces textes, et pour chacun donne une definition courte (1 phrase) en francais simple, accessible a un debutant.

Retourne UNIQUEMENT un JSON valide de la forme :
{{"glossaire": [{{"terme": "...", "definition": "..."}}, ...]}}"""

    models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-flash-latest"]
    response = call_gemini_with_retry(client, models, prompt, config, max_rounds=2, retry_delay=20)
    if response is None:
        print("[repair] tous les modeles indisponibles pour le glossaire")
        return processed

    try:
        text = (response.text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            from json_repair import repair_json
            payload = json.loads(repair_json(text))
        new_gloss = payload.get("glossaire") or []
        if new_gloss:
            processed["glossaire"] = new_gloss
            print(f"[repair] glossaire regenere : {len(new_gloss)} termes")
        else:
            print("[repair] glossaire toujours vide")
    except Exception as e:
        print(f"[repair] echec parsing glossaire : {e}")
    return processed


def validate_data_quality(processed):
    """Calcule des metriques de qualite sur les donnees traitees."""
    all_tweets = list(processed.get("highlights") or [])
    for items in (processed.get("by_category") or {}).values():
        all_tweets.extend(items)
    if not all_tweets:
        return {"translated_pct": 0, "with_decryptage_pct": 0, "total": 0}
    translated = sum(1 for t in all_tweets if not needs_retranslation(t))
    with_decryptage = sum(1 for t in all_tweets if t.get("decryptage"))
    return {
        "translated_pct": round(100 * translated / len(all_tweets)),
        "with_decryptage_pct": round(100 * with_decryptage / len(all_tweets)),
        "total": len(all_tweets),
        "needs_retranslation_count": len(all_tweets) - translated,
    }


def build_html():
    days = []
    for f in sorted(DATA_DIR.glob("[0-9]*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            days.append(data)
        except Exception as e:
            print(f"[build] ignore {f.name} : {e}")

    # Charger les donnees du watchdog (s'il existe)
    health_file = BASE / "health" / "health.json"
    health = {"runs": []}
    if health_file.exists():
        try:
            health = json.loads(health_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    out = HTML_TEMPLATE.replace(
        "__DATA_JSON__", json.dumps(days, ensure_ascii=False)
    ).replace(
        "__HEALTH_JSON__", json.dumps(health, ensure_ascii=False)
    )
    HTML_OUT.write_text(out, encoding="utf-8")
    print(f"[build] {HTML_OUT}  ({len(days)} jours, {len(health.get('runs', []))} runs watchdog)")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily AI Digest</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    max-width: 920px;
    margin: 0 auto;
    padding: 1.5em 1em 4em;
    background: #f5f5f7;
    color: #1d1d1f;
    line-height: 1.5;
  }
  header { margin-bottom: .6em; }
  h1 { font-size: 1.9em; margin: 0 0 .15em; }
  .subtitle { color: #6e6e73; font-size: .95em; }

  /* Date tabs */
  .date-tabs {
    display: flex; gap: .35em;
    overflow-x: auto;
    padding: .5em 0;
    scrollbar-width: thin;
  }
  .date-tab {
    padding: .45em .9em;
    background: white;
    border: 1px solid #d2d2d7;
    border-radius: 999px;
    cursor: pointer;
    white-space: nowrap;
    font-size: .82em;
    color: #1d1d1f;
    font-family: inherit;
    transition: all .15s;
  }
  .date-tab:hover { background: #fafafa; }
  .date-tab.active { background: #1d1d1f; color: white; border-color: #1d1d1f; }

  /* View nav (Accueil / Actu / Tips / Idees / Outils) */
  .view-nav {
    display: flex; gap: .4em;
    overflow-x: auto;
    padding: 1em 0;
    margin-bottom: 1.2em;
    border-top: 1px solid #e0e0e5;
    border-bottom: 1px solid #e0e0e5;
    margin-top: .5em;
    scrollbar-width: thin;
  }
  .view-tab {
    padding: .6em 1em;
    background: white;
    border: 1px solid #d2d2d7;
    border-radius: 10px;
    cursor: pointer;
    white-space: nowrap;
    font-size: .92em;
    color: #1d1d1f;
    font-family: inherit;
    display: inline-flex;
    align-items: center;
    gap: .4em;
    transition: all .15s;
  }
  .view-tab:hover { background: #f5f5f7; }
  .view-tab.active {
    background: #0071e3;
    color: white;
    border-color: #0071e3;
  }
  .view-tab .count {
    background: rgba(0,0,0,0.08);
    border-radius: 999px;
    padding: 0 .55em;
    font-size: .78em;
    font-weight: 600;
  }
  .view-tab.active .count {
    background: rgba(255,255,255,0.25);
  }

  /* Summary card */
  .summary {
    background: linear-gradient(135deg, #fff8e1, #fff3c4);
    padding: 1.1em 1.2em;
    border-radius: 14px;
    margin-bottom: 1.5em;
    border-left: 4px solid #f4b400;
    font-size: 1em;
  }
  .summary-label {
    text-transform: uppercase;
    letter-spacing: .06em;
    font-size: .72em;
    color: #9a7700;
    font-weight: 700;
    margin-bottom: .3em;
  }

  /* Per-category summary (au-dessus de chaque sous-page) */
  .cat-summary {
    background: white;
    border: 1px solid #e0e0e5;
    border-left: 4px solid #0071e3;
    padding: 1em 1.2em;
    border-radius: 12px;
    margin-bottom: 1.5em;
  }
  .cat-summary-label {
    text-transform: uppercase;
    letter-spacing: .06em;
    font-size: .72em;
    color: #0071e3;
    font-weight: 700;
    margin-bottom: .3em;
  }

  /* Statut systeme */
  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: .35em;
    padding: .35em .8em;
    border-radius: 999px;
    font-size: .82em;
    font-weight: 600;
    margin-left: .5em;
    vertical-align: middle;
  }
  .status-badge.ok    { background: #e8f5e9; color: #1b5e20; border: 1px solid #a5d6a7; }
  .status-badge.warn  { background: #fff3e0; color: #b25400; border: 1px solid #ffcc80; }
  .status-badge.fail  { background: #ffebee; color: #b71c1c; border: 1px solid #ef9a9a; }
  .status-details {
    background: white;
    border: 1px solid #e0e0e5;
    border-radius: 12px;
    padding: .9em 1.1em;
    margin-bottom: 1.5em;
    font-size: .88em;
  }
  .status-details summary {
    cursor: pointer;
    font-weight: 600;
    list-style: none;
  }
  .status-details summary::before {
    content: "\25B8";
    display: inline-block;
    margin-right: .35em;
    transition: transform .15s;
  }
  .status-details[open] summary::before { transform: rotate(90deg); }
  .status-row { display: flex; justify-content: space-between; padding: .25em 0; gap: 1em; }
  .status-row .label { color: #6e6e73; }
  .status-row .value { font-weight: 600; }

  /* Section labels */
  .section-label {
    font-size: 1.15em;
    font-weight: 700;
    margin: 1.8em 0 .9em;
    display: flex;
    align-items: center;
    gap: .4em;
  }

  /* Highlights */
  .highlight {
    background: linear-gradient(135deg, #fff5f5, #fff0e8);
    border-left: 4px solid #ff6b35;
    border-radius: 12px;
    padding: .9em 1.1em;
    margin-bottom: .7em;
  }
  .highlight-reason {
    display: flex; align-items: center; gap: .4em; flex-wrap: wrap;
    font-size: .78em; color: #cc4400; font-weight: 700;
    margin-bottom: .5em;
    text-transform: uppercase; letter-spacing: .04em;
  }
  .highlight-reason::before { content: "\2605"; font-size: 1.15em; }
  .highlight-cat-pill {
    display: inline-block;
    background: rgba(204,68,0,0.12);
    color: #cc4400;
    padding: .15em .55em;
    border-radius: 999px;
    font-size: .9em;
    font-weight: 700;
    margin-left: auto;
    text-transform: none;
    letter-spacing: 0;
  }

  /* Category cards on home */
  .cat-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: .8em;
    margin: .5em 0 2em;
  }
  .cat-card {
    background: white;
    border: 1px solid #e0e0e5;
    border-radius: 12px;
    padding: 1.1em 1.1em 1em;
    cursor: pointer;
    transition: all .15s;
    text-align: left;
    font-family: inherit;
    font-size: 1em;
    width: 100%;
  }
  .cat-card:hover {
    border-color: #0071e3;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,113,227,0.08);
  }
  .cat-card-emoji { font-size: 1.8em; line-height: 1; }
  .cat-card-label { font-weight: 700; margin: .35em 0 .1em; font-size: 1.05em; }
  .cat-card-count { color: #0071e3; font-size: .85em; font-weight: 600; }
  .cat-card-sample { color: #6e6e73; font-size: .78em; margin-top: .4em; line-height: 1.35; }

  /* Page title for category views */
  .page-title {
    display: flex; align-items: baseline; gap: .5em; flex-wrap: wrap;
    margin: 0 0 1.2em;
    font-size: 1.4em;
    font-weight: 700;
  }
  .page-title-count {
    color: #6e6e73;
    font-size: .68em;
    font-weight: normal;
  }

  /* Tweet card */
  .tweet {
    background: white;
    border-radius: 14px;
    padding: 1em 1.1em;
    margin-bottom: .8em;
    box-shadow: 0 1px 3px rgba(0,0,0,.05);
  }
  .tweet-head {
    display: flex; align-items: baseline; gap: .5em; flex-wrap: wrap;
    margin-bottom: .4em;
  }
  .author { font-weight: 600; }
  .handle { color: #6e6e73; font-size: .82em; }
  .text { margin: .2em 0 .5em; }
  .original {
    font-size: .82em; color: #6e6e73; font-style: italic;
    margin: .5em 0 0; padding-left: .7em;
    border-left: 2px solid #d2d2d7;
  }
  .original-label {
    font-style: normal; font-weight: 600; color: #888;
    text-transform: uppercase; font-size: .72em; letter-spacing: .04em;
  }
  .decryptage {
    background: #eef6ff;
    border-left: 3px solid #0071e3;
    padding: .55em .8em;
    border-radius: 6px;
    margin-top: .6em;
    font-size: .9em;
    color: #1d3a5c;
  }
  .decryptage-label {
    font-weight: 700;
    color: #0071e3;
    margin-right: .35em;
    font-size: .85em;
  }
  .link {
    display: inline-block; margin-top: .4em;
    color: #0071e3; text-decoration: none; font-size: .82em;
  }
  .link:hover { text-decoration: underline; }

  /* Glossaire */
  .glossaire {
    background: #f0f4ff;
    border-radius: 14px;
    padding: 1.2em 1.4em;
    margin-top: 2em;
    border: 1px solid #d0dcf0;
  }
  .glossaire h2 {
    font-size: 1.05em;
    margin: 0 0 .7em;
    color: #1d3a5c;
  }
  .glossaire dl { margin: 0; }
  .glossaire dt {
    font-weight: 700;
    color: #0050b3;
    margin-top: .7em;
    font-size: .95em;
  }
  .glossaire dt:first-child { margin-top: 0; }
  .glossaire dd {
    margin: .15em 0 0 0;
    color: #1d1d1f;
    font-size: .9em;
  }
  .glossaire.compact { padding: 1em 1.2em; margin-top: 2.5em; }
  .glossaire.compact h2 { font-size: 1em; }

  /* Misc */
  .empty {
    color: #6e6e73; font-style: italic; padding: 1em 0;
  }
  .failed {
    background: #fff5f5; border-left: 4px solid #d62b2b;
    padding: .8em 1em; border-radius: 10px;
    color: #7a1a1a; font-size: .85em; margin-top: 2em;
  }
</style>
</head>
<body>
<header>
  <h1>Daily AI Digest</h1>
  <div class="subtitle">Ce que disent les gros createurs/devs IA sur X &middot; <span id="todayLabel"></span></div>
</header>

<div id="dateTabs" class="date-tabs"></div>
<div id="viewNav" class="view-nav"></div>
<div id="content"></div>

<script>
const DATA = __DATA_JSON__;
const HEALTH = __HEALTH_JSON__;
const CATEGORIES = [
  { key: "actu",   label: "Actualite", emoji: "📰" },
  { key: "tips",   label: "Tips",      emoji: "💡" },
  { key: "idees",  label: "Idees",     emoji: "🧠" },
  { key: "outils", label: "Outils",    emoji: "🛠️" },
];

const STATE = { dayIdx: 0, view: "home" };

function esc(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function fmtDate(s) {
  try {
    const d = new Date(s + "T12:00:00");
    return d.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
  } catch(e) { return s; }
}
function shortDate(s) {
  try {
    const d = new Date(s + "T12:00:00");
    return d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
  } catch(e) { return s; }
}

function renderTweet(t, isHighlight) {
  const catLabel = isHighlight && t.category
    ? CATEGORIES.find(c => c.key === t.category)
    : null;
  return `<article class="${isHighlight ? "highlight" : "tweet"}">
    ${isHighlight && t.highlight_reason ? `<div class="highlight-reason">
      <span>${esc(t.highlight_reason)}</span>
      ${catLabel ? `<span class="highlight-cat-pill">${catLabel.emoji} ${catLabel.label}</span>` : ""}
    </div>` : ""}
    <div class="tweet-head">
      <span class="author">${esc(t.author_name || "")}</span>
      <span class="handle">@${esc((t.handle || "").replace(/^@+/, ""))}</span>
    </div>
    <div class="text">${esc(t.text_fr || t.text || "")}</div>
    ${t.decryptage ? `<div class="decryptage"><span class="decryptage-label">En clair :</span>${esc(t.decryptage)}</div>` : ""}
    ${t.text_original ? `<div class="original"><span class="original-label">VO :</span> ${esc(t.text_original)}</div>` : ""}
    ${t.link ? `<a class="link" href="${esc(t.link)}" target="_blank" rel="noopener">Voir sur X &rarr;</a>` : ""}
  </article>`;
}

function renderGlossaire(items, compact) {
  if (!items || !items.length) return "";
  let html = `<section class="glossaire${compact ? " compact" : ""}"><h2>Glossaire du jour</h2><dl>`;
  for (const g of items) {
    html += `<dt>${esc(g.terme || "")}</dt><dd>${esc(g.definition || "")}</dd>`;
  }
  html += `</dl></section>`;
  return html;
}

function getCategoryAuthors(items, maxNames) {
  if (!items || !items.length) return "";
  const allAuthors = new Set();
  for (const t of items) {
    if (t.author_name) allAuthors.add(t.author_name);
  }
  const list = Array.from(allAuthors);
  const head = list.slice(0, maxNames);
  const rest = list.length - head.length;
  return rest > 0
    ? head.join(", ") + " et " + rest + " autre" + (rest > 1 ? "s" : "")
    : head.join(", ");
}

function renderStatus(day) {
  const v = day.validation || {};
  const failed = (day.failed_accounts || []).length;
  const translated = v.translated_pct;
  const needsRetrans = v.needs_retranslation_count || 0;
  let level = "ok", label = "OK";
  if (translated < 90 || failed > 3 || needsRetrans > 5) { level = "warn"; label = "Avertissements"; }
  if (translated < 60 || !v.total) { level = "fail"; label = "Probleme"; }

  // Donnees watchdog
  const runs = (HEALTH && HEALTH.runs) || [];
  const lastRun = runs.length ? runs[runs.length - 1] : null;
  const lastRunTime = lastRun ? lastRun.timestamp : null;
  // Tendance 7 derniers jours : 1 emoji par jour (vert/jaune/rouge)
  const trend7 = compute7DayTrend(runs);
  // Fixes appliques cette semaine
  const oneWeekAgo = new Date(Date.now() - 7*24*3600*1000).toISOString();
  const fixesThisWeek = runs
    .filter(r => r.timestamp >= oneWeekAgo)
    .reduce((acc, r) => acc + (r.fixes_applied || []).filter(f => f.success).length, 0);

  let html = `<details class="status-details">
    <summary>Statut systeme <span class="status-badge ${level}">${label}</span></summary>
    <div class="status-row"><span class="label">Mise a jour</span><span class="value">${esc(day.processed_at || day.fetched_at || day.date)}</span></div>
    <div class="status-row"><span class="label">Tweets traites</span><span class="value">${v.total || 0}</span></div>
    <div class="status-row"><span class="label">Taux de traduction</span><span class="value">${translated != null ? translated + "%" : "?"}</span></div>
    <div class="status-row"><span class="label">Avec decryptage</span><span class="value">${v.with_decryptage_pct != null ? v.with_decryptage_pct + "%" : "?"}</span></div>
    <div class="status-row"><span class="label">Comptes non recuperes</span><span class="value">${failed > 0 ? failed + " (" + (day.failed_accounts || []).map(h => "@" + h).join(", ") + ")" : "0"}</span></div>
    ${needsRetrans > 0 ? `<div class="status-row"><span class="label">Restant a traduire</span><span class="value">${needsRetrans}</span></div>` : ""}
    ${lastRunTime ? `<div class="status-row" style="border-top:1px dashed #ccc;margin-top:.5em;padding-top:.5em;"><span class="label">Watchdog (derniere verif)</span><span class="value">${esc(lastRunTime)}</span></div>` : ""}
    ${trend7 ? `<div class="status-row"><span class="label">Tendance 7 jours</span><span class="value" style="letter-spacing:.15em;">${trend7}</span></div>` : ""}
    ${runs.length > 0 ? `<div class="status-row"><span class="label">Auto-corrections cette semaine</span><span class="value">${fixesThisWeek}</span></div>` : ""}
  </details>`;
  return html;
}

function compute7DayTrend(runs) {
  if (!runs.length) return "";
  // Pour chaque des 7 derniers jours, calculer le ratio de checks OK
  const byDay = {};
  for (const r of runs) {
    const day = r.timestamp.slice(0, 10);
    if (!byDay[day]) byDay[day] = { ok: 0, ko: 0 };
    if (r.all_ok) byDay[day].ok++;
    else byDay[day].ko++;
  }
  const today = new Date();
  let emoji = "";
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 24 * 3600 * 1000);
    const key = d.toISOString().slice(0, 10);
    const stats = byDay[key];
    if (!stats) emoji += "⚫";              // gris : aucune verif ce jour
    else if (stats.ko === 0) emoji += "🟢";  // vert : 100% OK
    else if (stats.ok === 0) emoji += "🔴";  // rouge : aucun succes
    else emoji += "🟡";                     // jaune : mix succes/echec
  }
  return emoji;
}

function renderHome(day) {
  const p = day.processed || {};
  let html = "";
  html += renderStatus(day);
  if (p.summary) {
    html += `<section class="summary">
      <div class="summary-label">Resume du jour</div>
      ${esc(p.summary)}
    </section>`;
  }
  if (p.highlights && p.highlights.length) {
    html += `<div class="section-label">A ne pas manquer</div>`;
    for (const t of p.highlights) html += renderTweet(t, true);
  }
  if (p.by_category) {
    html += `<div class="section-label">Explorer par categorie</div>`;
    html += `<div class="cat-cards">`;
    for (const cat of CATEGORIES) {
      const items = p.by_category[cat.key] || [];
      const sample = getCategoryAuthors(items, 3);
      html += `<button class="cat-card" data-cat="${cat.key}">
        <div class="cat-card-emoji">${cat.emoji}</div>
        <div class="cat-card-label">${cat.label}</div>
        <div class="cat-card-count">${items.length} publication${items.length > 1 ? "s" : ""}</div>
        ${sample ? `<div class="cat-card-sample">${esc(sample)}</div>` : ""}
      </button>`;
    }
    html += `</div>`;
  }
  if (p.glossaire) html += renderGlossaire(p.glossaire, false);
  return html;
}

function renderCategoryView(day, catKey) {
  const cat = CATEGORIES.find(c => c.key === catKey);
  if (!cat) return '<p class="empty">Categorie introuvable.</p>';
  const p = day.processed || {};
  const items = (p.by_category || {})[catKey] || [];
  const catSummary = (p.category_summaries || {})[catKey];
  let html = `<div class="page-title">
    <span>${cat.emoji} ${cat.label}</span>
    <span class="page-title-count">${items.length} publication${items.length > 1 ? "s" : ""}</span>
  </div>`;
  if (catSummary) {
    html += `<section class="cat-summary">
      <div class="cat-summary-label">En bref</div>
      ${esc(catSummary)}
    </section>`;
  }
  if (!items.length) {
    html += '<p class="empty">Aucune publication dans cette categorie aujourd\'hui.</p>';
  } else {
    for (const t of items) html += renderTweet(t, false);
  }
  if (p.glossaire) html += renderGlossaire(p.glossaire, true);
  return html;
}

function renderRawTweets(day) {
  let html = `<div class="page-title">
    <span>Tweets bruts</span>
    <span class="page-title-count">(non encore traites par l'IA)</span>
  </div>`;
  for (const t of day.tweets || []) {
    html += renderTweet({
      author_name: t.author_name, handle: t.handle,
      text_fr: t.text, link: t.link
    }, false);
  }
  return html;
}

function render() {
  const day = DATA[STATE.dayIdx];
  const content = document.getElementById("content");
  if (!day) {
    content.innerHTML = '<p class="empty">Aucune donnee.</p>';
    return;
  }
  document.getElementById("todayLabel").textContent = fmtDate(day.date);
  document.querySelectorAll(".date-tab").forEach((t, i) => {
    t.classList.toggle("active", i === STATE.dayIdx);
  });

  const viewNav = document.getElementById("viewNav");
  const p = day.processed || {};
  let viewNavHtml = `<button class="view-tab${STATE.view === "home" ? " active" : ""}" data-view="home">🏠 Accueil</button>`;
  for (const cat of CATEGORIES) {
    const items = (p.by_category || {})[cat.key] || [];
    const isActive = STATE.view === cat.key;
    viewNavHtml += `<button class="view-tab${isActive ? " active" : ""}" data-view="${cat.key}">
      ${cat.emoji} ${cat.label}
      <span class="count">${items.length}</span>
    </button>`;
  }
  viewNav.innerHTML = viewNavHtml;
  viewNav.querySelectorAll(".view-tab").forEach(btn => {
    btn.onclick = () => { STATE.view = btn.dataset.view; render(); window.scrollTo(0,0); };
  });

  let html = "";
  const hasProcessed = p.summary || p.by_category;
  if (!hasProcessed) {
    html = renderRawTweets(day);
  } else if (STATE.view === "home") {
    html = renderHome(day);
  } else {
    html = renderCategoryView(day, STATE.view);
  }

  if (day.failed_accounts && day.failed_accounts.length) {
    html += `<div class="failed"><b>Comptes non recuperes :</b> ${
      day.failed_accounts.map(h => "@" + esc(h)).join(", ")
    }</div>`;
  }
  content.innerHTML = html;

  content.querySelectorAll(".cat-card").forEach(btn => {
    btn.onclick = () => { STATE.view = btn.dataset.cat; render(); window.scrollTo(0,0); };
  });
}

(function init() {
  const dateTabsEl = document.getElementById("dateTabs");
  if (!DATA.length) {
    dateTabsEl.innerHTML = "";
    document.getElementById("content").innerHTML =
      '<p class="empty">Aucune donnee. Lance le script <code>digest.py</code> pour recuperer les tweets du jour.</p>';
    return;
  }
  DATA.forEach((day, i) => {
    const tab = document.createElement("button");
    tab.className = "date-tab" + (i === 0 ? " active" : "");
    tab.textContent = shortDate(day.date);
    tab.onclick = () => { STATE.dayIdx = i; render(); window.scrollTo(0,0); };
    dateTabsEl.appendChild(tab);
  });
  render();
})();
</script>
</body>
</html>
"""


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    today = datetime.now().strftime("%Y-%m-%d")
    day_file = DATA_DIR / f"{today}.json"

    if cmd in ("fetch", "all"):
        print("=== FETCH ===")
        fetch_all()

    if cmd in ("process", "all"):
        print("\n=== PROCESS ===")
        if day_file.exists():
            process_with_gemini(day_file)
        else:
            print(f"[process] pas de fichier {day_file}, lance d'abord 'fetch'")

    if cmd in ("build", "all"):
        print("\n=== BUILD ===")
        build_html()
        print(f"\nOuvre dans Chrome : file:///{HTML_OUT.as_posix()}")


if __name__ == "__main__":
    main()
