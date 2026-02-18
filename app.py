import os
import io
import glob
import csv
import re
import json
import time
import requests as http_requests
from flask import Flask, render_template, request
from dotenv import load_dotenv
from google import genai

# 1. Configuration
load_dotenv(override=True)
app = Flask(__name__)

os.environ.pop("GOOGLE_API_KEY", None)

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("Pas de clé API trouvée dans le fichier .env")

client = genai.Client(api_key=api_key)

# --- FONCTIONS DE CHARGEMENT CSV ---
def parser_csv(reader):
    """Parse un DictReader CSV et retourne une liste d'articles"""
    articles = []
    for ligne in reader:
        articles.append({
            "titre": ligne.get('Titre', 'Sans titre'),
            "description": ligne.get('Description', 'Pas de description'),
            "tags": ligne.get('Tags', ''),
            "url": ligne.get("URL", '#'),
        })
    return articles

def charger_articles():
    """Charge les articles depuis le Google Sheet (ou fallback CSV local)"""
    sheet_url = os.getenv("GOOGLE_SHEET_CSV_URL")

    if sheet_url:
        try:
            resp = http_requests.get(sheet_url, timeout=10)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            reader = csv.DictReader(io.StringIO(resp.text), delimiter=',')
            articles = parser_csv(reader)
            if articles:
                print(f"[SOURCE] Google Sheet chargé : {len(articles)} articles")
                return articles
        except Exception as e:
            print(f"[SOURCE] Erreur Google Sheet, fallback CSV local : {e}")

    dossier_sources = os.path.join(os.path.dirname(__file__), 'sources')
    fichiers = glob.glob(os.path.join(dossier_sources, "*.csv"))
    if not fichiers:
        return []

    try:
        with open(fichiers[0], mode='r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=',')
            articles = parser_csv(reader)
            print(f"[SOURCE] CSV local chargé : {len(articles)} articles")
            return articles
    except Exception:
        return []

def construire_contexte(articles):
    """Construit le contexte texte pour l'IA (sans les URLs)"""
    contexte = ""
    for i, art in enumerate(articles):
        contexte += f"""
--- ARTICLE {i + 1} ---
TITRE : {art['titre']}
DESCRIPTION : {art['description']}
TAGS : {art['tags']}
----------------
"""
    return contexte

def extraire_tags_uniques(articles):
    """Extrait la liste des tags uniques"""
    tags_set = set()
    for art in articles:
        for tag in art['tags'].split(','):
            tag = tag.strip()
            if tag:
                tags_set.add(tag)
    return sorted(tags_set, key=str.lower)

# 2. Cache avec rechargement automatique (TTL = 5 minutes)
CACHE_TTL = 300
_cache = {
    "articles": [],
    "tags": [],
    "last_refresh": 0,
}

def get_donnees():
    """Retourne les articles et tags, recharge depuis le Sheet si le cache a expiré"""
    now = time.time()
    if now - _cache["last_refresh"] > CACHE_TTL or not _cache["articles"]:
        articles = charger_articles()
        _cache["articles"] = articles
        _cache["tags"] = extraire_tags_uniques(articles)
        _cache["last_refresh"] = now
    return _cache["articles"], _cache["tags"]

def build_system_instruction(articles):
    contexte = construire_contexte(articles)
    return f"""
Tu es un assistant de recherche bibliographique interne.
Ton rôle est de trouver les articles les plus pertinents dans la base de données fournie ci-dessous.

BASE DE DONNÉES :
{contexte}

RÈGLES DE RÉPONSE :
1. Si aucun article ne correspond, réponds exactement : []
2. Si tu trouves des articles pertinents, retourne UNIQUEMENT un tableau JSON avec les TITRES EXACTS des articles trouvés.
3. Exemple de réponse attendue : ["Titre article 1", "Titre article 2"]
4. Les titres doivent correspondre EXACTEMENT à ceux de la base (copie-les caractère par caractère).
5. Ne retourne RIEN d'autre que le tableau JSON. Pas de texte, pas d'explication, pas de markdown.
"""

def construire_html_resultats(titres_trouves, articles):
    """Construit le HTML des cards à partir des titres retournés par l'IA"""
    html = ""
    for titre in titres_trouves:
        article = next((a for a in articles if a['titre'].strip().lower() == titre.strip().lower()), None)
        if article:
            url = article['url'].strip()
            has_url = url and url != '#'
            btn = f'<a href="{url}" target="_blank" class="btn-read">Lire l\'article &rarr;</a>' if has_url else ''
            html += f"""
<div class="article-card">
    <h3>{article['titre']}</h3>
    <p class="tags">🏷️ {article['tags']}</p>
    <p class="description">{article['description']}</p>
    {btn}
</div>
"""
    return html if html else "<p>Aucun article correspondant trouvé dans la base.</p>"

# 3. Route Flask
@app.route('/', methods=['GET', 'POST'])
def home():
    articles, tags = get_donnees()
    resultat = None
    question = ""

    if request.method == 'POST':
        question = request.form.get('question')
        if question:
            try:
                instruction = build_system_instruction(articles)
                response = client.models.generate_content(
                    model="gemini-2.0-flash-lite",
                    config={
                        "system_instruction": instruction,
                        "http_options": {"timeout": 60000},
                    },
                    contents=question
                )
                raw = response.text.strip()
                raw = re.sub(r'```json\s*', '', raw)
                raw = re.sub(r'```\s*', '', raw)
                raw = raw.strip()

                titres = json.loads(raw)
                if isinstance(titres, list) and len(titres) > 0:
                    resultat = construire_html_resultats(titres, articles)
                else:
                    resultat = "<p>Aucun article correspondant trouvé dans la base.</p>"
            except json.JSONDecodeError:
                resultat = "<p>Aucun article correspondant trouvé dans la base.</p>"
            except Exception as e:
                resultat = f"<p style='color:red'>Erreur : {str(e)}</p>"

    return render_template('index.html', resultat=resultat, question=question, tags=tags, nb_articles=len(articles))

if __name__ == '__main__':
    print("CSV chargé. Serveur prêt.")
    app.run(debug=True, port=5000)
