import os
import glob
import csv
import re
import json
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
def charger_articles():
    """Lit le CSV et retourne une liste de dictionnaires avec toutes les infos"""
    articles = []
    dossier_sources = os.path.join(os.path.dirname(__file__), 'sources')
    fichiers = glob.glob(os.path.join(dossier_sources, "*.csv"))

    if not fichiers:
        return []

    try:
        with open(fichiers[0], mode='r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=',')
            for ligne in reader:
                articles.append({
                    "titre": ligne.get('Titre', 'Sans titre'),
                    "description": ligne.get('Description', 'Pas de description'),
                    "tags": ligne.get('Tags', ''),
                    "url": ligne.get("URL", '#'),
                })
    except Exception:
        return []

    return articles

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

# 2. Initialisation
articles_db = charger_articles()
liste_tags = extraire_tags_uniques(articles_db)
contexte_csv = construire_contexte(articles_db)

SYSTEM_INSTRUCTION = f"""
Tu es un assistant de recherche bibliographique interne.
Ton rôle est de trouver les articles les plus pertinents dans la base de données fournie ci-dessous.

BASE DE DONNÉES :
{contexte_csv}

RÈGLES DE RÉPONSE :
1. Si aucun article ne correspond, réponds exactement : []
2. Si tu trouves des articles pertinents, retourne UNIQUEMENT un tableau JSON avec les TITRES EXACTS des articles trouvés.
3. Exemple de réponse attendue : ["Titre article 1", "Titre article 2"]
4. Les titres doivent correspondre EXACTEMENT à ceux de la base (copie-les caractère par caractère).
5. Ne retourne RIEN d'autre que le tableau JSON. Pas de texte, pas d'explication, pas de markdown.
"""

def construire_html_resultats(titres_trouves):
    """Construit le HTML des cards à partir des titres retournés par l'IA"""
    html = ""
    for titre in titres_trouves:
        article = next((a for a in articles_db if a['titre'].strip().lower() == titre.strip().lower()), None)
        if article:
            html += f"""
<div class="article-card">
    <h3>{article['titre']}</h3>
    <p class="tags">🏷️ {article['tags']}</p>
    <p class="description">{article['description']}</p>
    <a href="{article['url']}" target="_blank" class="btn-read">Lire l'article &rarr;</a>
</div>
"""
    return html if html else "<p>Aucun article correspondant trouvé dans la base.</p>"

# 3. Route Flask
@app.route('/', methods=['GET', 'POST'])
def home():
    resultat = None
    question = ""

    if request.method == 'POST':
        question = request.form.get('question')
        if question:
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash-lite",
                    config={
                        "system_instruction": SYSTEM_INSTRUCTION,
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
                    resultat = construire_html_resultats(titres)
                else:
                    resultat = "<p>Aucun article correspondant trouvé dans la base.</p>"
            except json.JSONDecodeError:
                resultat = "<p>Aucun article correspondant trouvé dans la base.</p>"
            except Exception as e:
                resultat = f"<p style='color:red'>Erreur : {str(e)}</p>"

    return render_template('index.html', resultat=resultat, question=question, tags=liste_tags)

if __name__ == '__main__':
    print("CSV chargé. Serveur prêt.")
    app.run(debug=True, port=5000)
