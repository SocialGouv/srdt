import httpx
import os


def get_extended_data(message: str, is_summary: bool) -> str:
    summary_prompt = "Tu es un chatbot expert en droit du travail français. Lis le texte donné et rédige un résumé clair, précis et concis, limité à 4096 tokens maximum. Dans ce résumé, fais ressortir les points clés suivants : Sujets principaux : identifie les droits et obligations des employeurs et des salariés, les conditions de travail, les procédures, etc. Langage clair : simplifie le langage juridique tout en restant précis pour éviter toute confusion. Organisation logique : commence par les informations principales, puis détaille les exceptions ou points secondaires s'ils existent. Neutralité : garde un ton factuel, sans jugement ou interprétation subjective. Longueur : si le texte est long, privilégie les informations essentielles pour respecter la limite de 4096 tokens. Ta réponse doit obligatoirement être en français."
    keyword_prompt = "Tu es un chatbot expert en droit du travail français. Ta seule mission est d’extraire une liste de mots-clés à partir du texte fourni. Objectif : Les mots-clés doivent refléter les idées et thèmes principaux pour faciliter la compréhension et la recherche du contenu du texte. Sélection : Extrait uniquement les termes essentiels, comme les droits et devoirs des employeurs et des salariés, les conditions de travail, les procédures, les sanctions, etc. Non-redondance : Évite les répétitions ; chaque mot-clé doit apparaître une seule fois. Clarté et simplicité : Assure-toi que chaque mot-clé est compréhensible et pertinent. Format attendu pour la liste de mots-clés : une liste simple et directe, sans organisation par thèmes, comme dans cet exemple : code du travail, article 12, congés payés, heures supplémentaires, licenciement économique. Ta réponse doit obligatoirement être en français."

    api_key = os.getenv("ALBERT_API_KEY")
    if not api_key:
        raise ValueError("API key for Albert is not set")

    try:
        response = httpx.post(
            "https://albert.api.etalab.gouv.fr/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": summary_prompt if is_summary else keyword_prompt,
                    },
                    {
                        "role": "user",
                        "content": message,
                    },
                ],
                "model": "meta-llama/Meta-Llama-3.1-70B-Instruct",
            },
        )
        response.raise_for_status()
        chat_response = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"Request failed: {e.response.status_code} - {e.response.text}"
        )
    except Exception as e:
        raise RuntimeError(f"An error occurred: {str(e)}")

    return chat_response
