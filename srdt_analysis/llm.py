import ollama


def get_extended_data(message: str, is_summary: bool) -> str:
    summary_prompt = "Tu es un chatbot expert en droit du travail français. Lis le texte donné et rédige un résumé clair, précis et concis, limité à 4096 tokens maximum. Dans ce résumé, fais ressortir les points clés suivants : Sujets principaux : identifie les droits et obligations des employeurs et des salariés, les conditions de travail, les procédures, etc. Langage clair : simplifie le langage juridique tout en restant précis pour éviter toute confusion. Organisation logique : commence par les informations principales, puis détaille les exceptions ou points secondaires s'ils existent. Neutralité : garde un ton factuel, sans jugement ou interprétation subjective. Longueur : si le texte est long, privilégie les informations essentielles pour respecter la limite de 4096 tokens."
    keyword_prompt = "Tu es un chatbot expert en droit du travail français. Ta seule mission est d’extraire une liste de mots-clés à partir du texte fourni. Objectif : Les mots-clés doivent refléter les idées et thèmes principaux pour faciliter la compréhension et la recherche du contenu du texte. Sélection : Extrait uniquement les termes essentiels, comme les droits et devoirs des employeurs et des salariés, les conditions de travail, les procédures, les sanctions, etc. Non-redondance : Évite les répétitions ; chaque mot-clé doit apparaître une seule fois. Clarté et simplicité : Assure-toi que chaque mot-clé est compréhensible et pertinent. Format attendu pour la liste de mots-clés : une liste simple et directe, sans organisation par thèmes, comme dans cet exemple : code du travail, article 12, congés payés, heures supplémentaires, licenciement économique"
    response = ollama.chat(
        model="mistral-nemo",
        messages=[
            {
                "role": "system",
                "content": summary_prompt if is_summary else keyword_prompt,
            },
            {
                "role": "user",
                "content": message,
            },
        ],
    )
    return response["message"]["content"]
