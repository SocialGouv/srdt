from mistralai import Mistral
import openai
from openai import OpenAI
from instructions_LLM import instructions
from functions_pipeline_rag_test import all
import json
import requests
from API_KEYS import keys

def call_LLM(user_prompt: str, instructions_prompt: str, LLM_model_family: str, LLM_model_version: str,) -> str:
    """
    Appelle l'API OpenAI pour interagir avec un modèle GPT (par exemple GPT-4).

    :param question_utilisateur: La question ou le contexte de l'utilisateur.
    :param instructions_prompt: Les instructions spécifiques à fournir au modèle.    
    :param LLM_model_family: entre chatgpr, mistral et albert.
    :param LLM_model_version: la version de tests de l'asistant juridique global'.    
    :return: La réponse générée par le modèle sous forme de texte.
    """
    api_key = keys[LLM_model_family.upper() + "_KEY"]
    data = {"model" : LLM_model_version,  
            'messages' : [
                {"role": "system", "content": instructions_prompt},
                {"role": "user", "content": question_utilisateur}
            ]}


    # Appel de la bonne api (3 choix possibles)        

    if LLM_model_family == 'chatgpt':

        openai.api_key = api_key
        # Appel de l'API
        response = openai.chat.completions.create(**data)       


    elif LLM_model_family == 'mistral':

        client = Mistral(api_key=api_key)            
        response = client.chat.complete(**data)       

    elif LLM_model_family == 'albert':

        base_url = "https://albert.api.etalab.gouv.fr/v1"
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(**data)

    # Extraction de la réponse du modèle
    return response.choices[0].message.content.strip()



def albert_search(collections: list, query: str, k: int) -> list:
    """  
    :return: le top K des chunks en résultat du search Albert sur la query : contenu du chunk, titre du document, url du document
    """
    base_url = "https://albert.api.etalab.gouv.fr/v1"
    api_key = ALBERT_KEY
    data = {'collections':collections,
        'k':k,
        'prompt':query}
    session = requests.session()
    session.headers = {"Authorization": f"Bearer {api_key}"}
    response = session.post(url=f"{base_url}/search", json=data, headers={"Authorization": f"Bearer {api_key}"})

    return response.json()["data"]


def pipeline_test_RAG(instructions, LLM, question_utilisateur):
    """
    :return: retourne la réponse de l'assistant, la liste des url sources, et les id des documents sources, et la question reformulée
    """
    # 1ère étape : anonymiser avec Albert
    anonymized_question = call_LLM(user_prompt=question_utilisateur, 
        instructions_prompt=instructions['anonymisation'],
        LLM_model_family='albert',
        LLM_model_version='meta-llama/Meta-Llama-3.1-70B-Instruct'
        )

    # 2ème étape : reformuler la question
    rephrased_question = call_LLM(user_prompt=anonymized_question, 
        instructions_prompt=instructions['reformulation'],
        LLM_model_family=LLM['llm_model_family'],
        LLM_model_version=LLM['llm_model_version']
        )

    # 3ème étape : séparer la question en multiple queries
    multiple_queries = call_LLM(user_prompt=rephrased_question, 
        instructions_prompt=instructions['split_multiple_queries'],
        LLM_model_family=LLM['llm_model_family'],
        LLM_model_version=LLM['llm_model_version']
        )
    multiple_queries = json.loads(multiple_queries)


    # 4ème étape : aller chercher le top K des chunks par query dans les collections Albert
    top_chunks = list()
    for _i in range(len(multiple_queries.keys())):
        _query = multiple_queries[list(multiple_queries.keys())[_i]]
        top_chunks = top_chunks + albert_search(collections=collections_albert, query=_query, k=top_K)


    # 5ème étape : rajouter les chunks à l'instruction
    final_instruction = instructions['final_instruction']
    sources_id = list()
    sources_url = list()
    sources_contenu = dict()

    for _i in range(len(top_chunks)):
        if top_chunks[_i]['chunk']['metadata']['document_id'] not in sources_id : sources_id.append(top_chunks[_i]['chunk']['metadata']['document_id'])
        if top_chunks[_i]['chunk']['metadata']['url'] not in sources_url : sources_url.append(top_chunks[_i]['chunk']['metadata']['url'])
        if top_chunks[_i]['chunk']['metadata']['document_name'] not in sources_contenu.keys() :
            sources_contenu[top_chunks[_i]['chunk']['metadata']['document_name']] = list()
            sources_contenu[top_chunks[_i]['chunk']['metadata']['document_name']].append(top_chunks[_i]['chunk']['content'])

    for _j in range(len(sources_contenu.keys())):
        _titre = list(sources_contenu.keys())[_j]
        _chunk =  "\n ### Titre du document : " + _titre + "\n"
        for _k in range(len(sources_contenu[_titre])):
            _extrait = sources_contenu[_titre][_k]
            _chunk = _chunk + "\n\n" + _extrait +  "\n\n"
        final_instruction = final_instruction + _chunk

    # 6ème étape : appeler le LLM pour obtenir la réponse
    reponse_assistant = call_LLM(user_prompt=rephrased_question, 
        instructions_prompt=final_instruction, 
        LLM_model_family=LLM['llm_model_family'],
        LLM_model_version=LLM['llm_model_version'])

    return {'reponse_assistant' : reponse_assistant,
            'urls' : sources_url,
            'documents_id' : sources_id
            'question_reformulee' : rephrased_question
            }
