# Daily AI Digest

Recupere chaque matin les tweets des plus gros createurs/devs IA, les traduit en francais et les synthetise par categorie. Tout est 100% gratuit.

## Installation (une seule fois)

### 1. Verifier Python

```cmd
python --version
```

Si Python n'est pas installe : https://www.python.org/downloads/ (cocher "Add Python to PATH" pendant l'install).

### 2. Installer la dependance Gemini

```cmd
cd C:\Users\centu\x-ai-digest
pip install -r requirements.txt
```

### 3. Obtenir une cle API Gemini (gratuite, sans CB)

- Aller sur https://aistudio.google.com/apikey
- Se connecter avec un compte Google
- Cliquer "Create API key"
- Copier la cle

### 4. Enregistrer la cle dans les variables d'environnement

Dans une invite de commandes :

```cmd
setx GEMINI_API_KEY "colle_ta_cle_ici"
```

**Important** : fermer puis rouvrir le terminal pour que la variable soit prise en compte.

## Utilisation quotidienne

Double-clique sur `run.bat`.

Le script :
1. Recupere les tweets via Nitter (instances publiques RSS)
2. Appelle Gemini pour traduire en FR + classer (actu / tips / idees / outils)
3. Met a jour `index.html`
4. Ouvre la page dans Chrome

Chaque jour devient un onglet dans la page.

## Automatisation (optionnelle)

Pour lancer automatiquement chaque matin via Windows Task Scheduler :

1. `Win + R` -> `taskschd.msc`
2. "Creer une tache de base"
3. Declencheur : quotidien, ex. 08:00
4. Action : "Demarrer un programme"
5. Programme : `C:\Users\centu\x-ai-digest\run.bat`
6. Cocher "Executer meme si l'utilisateur n'est pas connecte" si voulu

## Si les tweets ne se recuperent pas

Les instances Nitter publiques peuvent etre temporairement inaccessibles. Dans ce cas :
- Relancer le script plus tard
- Ou editer la liste `NITTER_INSTANCES` dans `digest.py` pour ajouter d'autres instances (cf. https://status.d420.de/)
- Solution payante de secours : un service comme Apify (~10$/mois)

## Modifier la liste des comptes

Editer `accounts.json`. Chaque entree :
```json
{"handle": "karpathy", "name": "Andrej Karpathy", "category": "researcher", "lang": "en"}
```

## Structure des fichiers

```
x-ai-digest/
  accounts.json         <- liste des comptes a suivre
  digest.py             <- script principal
  index.html            <- page web a ouvrir chaque matin
  run.bat               <- lanceur Windows
  data/
    2026-05-11.json     <- donnees brutes + traitees du jour
    2026-05-12.json
    ...
```
