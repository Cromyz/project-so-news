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
    """Parse un DictReader CSV et retourne une liste d'articles.
    Format attendu : ID, Titre, Description, Tags, URL (ou Titre, Description, Tags, URL en rétrocompatibilité).
    """
    articles = []
    for i, ligne in enumerate(reader):
        raw_id = (ligne.get('ID') or '').strip()
        raw_titre = (ligne.get('Titre') or '').strip()
        raw_desc = (ligne.get('Description') or '').strip()
        raw_tags = (ligne.get('Tags') or '').strip()
        raw_url = (ligne.get('URL') or '#').strip()
        articles.append({
            "id": raw_id if raw_id else str(i),
            "titre": raw_titre if raw_titre else "Article sans titre",
            "description": raw_desc if raw_desc else "Aucune description disponible",
            "tags": raw_tags,
            "url": raw_url if raw_url else '#',
        })
    return articles

def charger_articles():
    """Charge les articles depuis le Google Sheet (ou fallback CSV local)"""
    sheet_url = os.getenv("GOOGLE_SHEET_CSV_URL")

    print(f"[SOURCE] GOOGLE_SHEET_CSV_URL = '{sheet_url}'")

    if sheet_url:
        try:
            resp = http_requests.get(sheet_url.strip(), timeout=15)
            print(f"[SOURCE] HTTP status: {resp.status_code}, taille: {len(resp.text)} chars")
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            reader = csv.DictReader(io.StringIO(resp.text), delimiter=',')
            articles = parser_csv(reader)
            if articles:
                print(f"[SOURCE] Google Sheet chargé : {len(articles)} articles")
                return articles
            else:
                print(f"[SOURCE] Google Sheet vide, fallback CSV local")
        except Exception as e:
            print(f"[SOURCE] Erreur Google Sheet, fallback CSV local : {e}")
    else:
        print("[SOURCE] Pas de GOOGLE_SHEET_CSV_URL, utilisation du CSV local")

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
    """Construit le contexte texte pour l'IA (sans les URLs), inclut l'ID pour le matching."""
    contexte = ""
    for i, art in enumerate(articles):
        contexte += f"""
--- ARTICLE {i + 1} ---
ID : {art['id']}
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


def rechercher_par_tag_exact(question, articles, tags):
    """Si la requête correspond exactement à un tag, retourne les IDs des articles sans appeler l'API."""
    q = question.strip().lower()
    if not q or q not in {t.lower() for t in tags}:
        return None
    ids = []
    for art in articles:
        art_tags = [t.strip().lower() for t in art['tags'].split(',') if t.strip()]
        if q in art_tags:
            ids.append(str(art['id']))
    return ids

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

def build_system_instruction(articles, feedback=None):
    contexte = construire_contexte(articles)
    feedback_block = ""
    if feedback:
        feedback_block = f"\nRETOUR DU VÉRIFICATEUR (à corriger) : {feedback}\n"
    return f"""Tu es un assistant de recherche bibliographique.
{feedback_block}
BASE DE DONNÉES :
{contexte}

RÈGLES :
1. Comprends la question en langage naturel.
2. Retourne UNIQUEMENT un JSON : {{"ids": ["id1", "id2", ...]}} avec les IDs des articles pertinents.
3. Si aucun article : {{"ids": []}}
4. IDs doivent correspondre EXACTEMENT à la colonne ID de la base.
5. Max 5 articles. Pas de texte, pas de synthèse, pas de markdown."""

def construire_html_resultats(ids_trouves, articles):
    """Construit le HTML des cards à partir des IDs retournés par l'IA. Match par id (prioritaire)."""
    ids_str = {str(x).strip() for x in ids_trouves}
    html = ""
    for art_id in ids_trouves:
        art_id_str = str(art_id).strip()
        article = next((a for a in articles if str(a['id']).strip() == art_id_str), None)
        if not article:
            # Fallback: match par titre si id non trouvé (rétrocompatibilité)
            article = next((a for a in articles if a['titre'].strip().lower() == str(art_id).strip().lower()), None)
        if article:
            url = article['url'].strip()
            has_url = url and url != '#'
            btn = f'<a href="{url}" target="_blank" class="btn-read">Lire l\'article &rarr;</a>' if has_url else ''
            desc_display = article['description'] if article['description'] != "Aucune description disponible" else "—"
            tags_display = f"🏷️ {article['tags']}" if article['tags'] else ""
            html += f"""
<div class="article-card">
    <h3>{article['titre']}</h3>
    {f'<p class="tags">{tags_display}</p>' if tags_display else ''}
    <p class="description">{desc_display}</p>
    {btn}
</div>
"""
    return html if html else "<p>Aucun article correspondant trouvé dans la base.</p>"


def extraire_json_reponse(raw_text):
    """Extrait le JSON de la réponse brute (gère markdown, préfixes, etc.)."""
    raw = raw_text.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*', '', raw)
    raw = re.sub(r'\s*```\s*$', '', raw)
    raw = raw.strip()
    return raw


def agent_principal(question, articles, feedback=None):
    """Appelle l'agent Gemini pour produire une liste d'IDs d'articles pertinents."""
    instruction = build_system_instruction(articles, feedback=feedback)
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        config={
            "system_instruction": instruction,
            "http_options": {"timeout": 60000},
        },
        contents=question,
    )
    raw = extraire_json_reponse(response.text)
    data = json.loads(raw)

    if isinstance(data, list):
        ids_valides = {str(a["id"]).strip() for a in articles}
        ids = [str(x).strip() for x in data if str(x).strip() in ids_valides]
        return {"ids": ids}

    ids = data.get("ids", [])
    if not isinstance(ids, list):
        ids = []
    return {"ids": ids}


def agent_verificateur(reponse_brute, articles, question):
    """Vérifie que les IDs retournés existent dans la base."""
    ids_demandes = reponse_brute.get("ids", [])
    ids_valides = {str(a["id"]).strip() for a in articles}

    ids_invalides = [x for x in ids_demandes if str(x).strip() not in ids_valides]
    if ids_invalides:
        return {
            "valid": False,
            "feedback": f"IDs invalides : {ids_invalides}. Utilise uniquement des IDs de la base.",
        }

    return {"valid": True, "reponse": reponse_brute}


# 3. Route Flask
MAX_ITERATIONS = 2


@app.route('/', methods=['GET', 'POST'])
def home():
    articles, tags = get_donnees()
    resultat = None
    question = ""
    nb_resultats = 0

    if request.method == 'POST':
        question = request.form.get('question', '').strip()
        cleaned = re.sub(r'[^a-zA-ZÀ-ÿ0-9\s]', '', question).strip()

        if not cleaned or len(cleaned) < 2:
            resultat = "<p>Veuillez saisir une recherche valide (au moins 2 caractères).</p>"
            nb_resultats = 0
        elif question:
            try:
                ids = rechercher_par_tag_exact(question, articles, tags)
                if ids is not None:
                    resultat = construire_html_resultats(ids, articles) if ids else "<p class='no-results'>Aucun article correspondant trouvé dans la base.</p>"
                    nb_resultats = len(ids)
                else:
                    reponse_brute = agent_principal(question, articles)
                    verification = agent_verificateur(reponse_brute, articles, question)
                    iteration = 1

                    while not verification["valid"] and iteration < MAX_ITERATIONS:
                        reponse_brute = agent_principal(question, articles, feedback=verification["feedback"])
                        verification = agent_verificateur(reponse_brute, articles, question)
                        iteration += 1

                    ids = verification["reponse"]["ids"] if verification["valid"] else reponse_brute.get("ids", [])
                    resultat = construire_html_resultats(ids, articles) if ids else "<p class='no-results'>Aucun article correspondant trouvé dans la base.</p>"
                    nb_resultats = len(ids)
            except json.JSONDecodeError as e:
                resultat = f"<p style='color:red'>Erreur de format de réponse : {str(e)}</p>"
                nb_resultats = 0
            except Exception as e:
                resultat = f"<p style='color:red'>Erreur : {str(e)}</p>"
                nb_resultats = 0

    return render_template(
        'index.html',
        resultat=resultat,
        question=question,
        tags=tags,
        nb_articles=len(articles),
        nb_resultats=nb_resultats,
    )

if __name__ == '__main__':
    print("CSV chargé. Serveur prêt.")
    app.run(debug=True, port=5000)
