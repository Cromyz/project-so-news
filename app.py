import os
import glob
import csv
import asyncio
from flask import Flask, render_template, request
from dotenv import load_dotenv

# Imports Google ADK
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.runners import InMemoryRunner

# 1. Configuration
load_dotenv()
app = Flask(__name__)

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("Pas de clé API trouvée dans le fichier .env")
os.environ["GOOGLE_API_KEY"] = api_key

# --- FONCTION DE CHARGEMENT CSV ---
def charger_base_connaissance():
    """Lit le fichier CSV dans le dossier /sources"""
    contenu_structure = ""
    dossier_sources = os.path.join(os.path.dirname(__file__), 'sources')
    
    # Liste les fichiers .csv
    fichiers = glob.glob(os.path.join(dossier_sources, "*.csv"))
    
    if not fichiers:
        return "Aucun fichier .csv trouvé dans le dossier sources."

    # On prend le premier fichier CSV trouvé
    fichier_cible = fichiers[0]
    nom_fichier = os.path.basename(fichier_cible)

    try:
        # Ouverture du fichier CSV (encodage utf-8-sig pour gérer les accents Excel)
        with open(fichier_cible, mode='r', encoding='utf-8-sig') as csvfile:
            # On utilise DictReader pour utiliser les noms de colonnes
            reader = csv.DictReader(csvfile, delimiter=',') # Change delimiter=';' si ton CSV vient d'un Excel français sans conversion
            
            contenu_structure += f"SOURCE DE DONNÉES : {nom_fichier}\n\n"
            
            for ligne in reader:
                # On formate chaque ligne pour que l'IA comprenne bien
                # On vérifie que les clés existent pour éviter les erreurs si le CSV est mal formé
                titre = ligne.get('Titre', 'Sans titre')
                desc = ligne.get('Description', 'Pas de description')
                tags = ligne.get('Tags', '')
                url = ligne.get("URL de l'article", '#')

                contenu_structure += f"""
--- ARTICLE ---
TITRE : {titre}
DESCRIPTION : {desc}
TAGS : {tags}
URL : {url}
----------------
"""
    except Exception as e:
        return f"Erreur critique lors de la lecture du CSV : {str(e)}"
            
    return contenu_structure

# 2. Initialisation de l'Agent
contexte_csv = charger_base_connaissance()

# Définition de l'Agent de Recherche
search_agent = Agent(
    name="search_assistant",
    model=Gemini(model="gemini-2.5-flash-lite"),
    instruction=f"""
    Tu es un assistant de recherche bibliographique interne.
    Ton rôle est de trouver les articles les plus pertinents dans la base de données CSV fournie ci-dessous pour répondre à la demande de l'utilisateur.

    BASE DE DONNÉES (Format CSV converti) :
    {contexte_csv}

    RÈGLES DE RÉPONSE :
    1. Si aucun article ne correspond, dis simplement : "Je n'ai pas trouvé d'article correspondant dans la base."
    2. Si tu trouves des articles pertinents, présente-les sous forme de liste HTML.
    3. Pour chaque article trouvé, utilise OBLIGATOIREMENT ce format HTML précis :
       
       <div class="mb-4 p-4 border rounded bg-white">
           <h3 class="font-bold text-lg text-indigo-600">[TITRE DE L'ARTICLE]</h3>
           <p class="text-sm text-gray-600 mb-2">🏷️ <em>[TAGS]</em></p>
           <p class="text-gray-800 mb-3">[DESCRIPTION]</p>
           <a href="[URL]" target="_blank" class="inline-block bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700">Lire l'article &rarr;</a>
       </div>

    4. Ne change pas les URLs, elles sont critiques.
    5. Sois synthétique. Ne rajoute pas de blabla avant ou après la liste.
    """
)

# 3. Route Flask
@app.route('/', methods=['GET', 'POST'])
async def home():
    resultat = None
    question = ""
    
    if request.method == 'POST':
        question = request.form.get('question')
        if question:
            try:
                runner = InMemoryRunner(agent=search_agent)
                response = await runner.run_debug(question)
                
                for event in reversed(response):
                    if event.content.role == "model" and event.content.parts:
                        resultat = event.content.parts[0].text
                        break
            except Exception as e:
                resultat = f"<p style='color:red'>Erreur : {str(e)}</p>"

    return render_template('index.html', resultat=resultat, question=question)

if __name__ == '__main__':
    print("CSV chargé. Serveur prêt.")
    app.run(debug=True, port=5000)