import os
import time

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from srdt_analysis.api.schemas import (
    AnonymizeRequest,
    AnonymizeResponse,
    ChunkMetadata,
    ChunkResult,
    GenerateRequest,
    GenerateResponse,
    RephraseRequest,
    RephraseResponse,
    SearchRequest,
    SearchResponse,
)
from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.constants import BASE_API_URL, COLLECTION_IDS
from srdt_analysis.llm_runner import LLMRunner
from srdt_analysis.tokenizer import Tokenizer

app = FastAPI()
api_key_header = APIKeyHeader(name="Authorization", auto_error=True)


async def get_api_key(api_key: str = Security(api_key_header)):
    if not api_key.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Must start with 'Bearer '",
        )
    token = api_key.replace("Bearer ", "")
    if token != os.getenv("API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "https://*.social.gouv.fr",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/")
@app.get(f"{BASE_API_URL}/")
async def root(api_key: str = Depends(get_api_key)):
    return {"status": "ok", "path": BASE_API_URL}


@app.post(f"{BASE_API_URL}/anonymize", response_model=AnonymizeResponse)
async def anonymize(request: AnonymizeRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner()
    try:
        anonymized_question = await llm_runner.anonymize(
            request.user_question, request.anonymization_prompt
        )
        return AnonymizeResponse(
            time=time.time() - start_time,
            anonymized_question=anonymized_question,
            nb_token_input=tokenizer.compute_nb_tokens(request.user_question),
            nb_token_output=tokenizer.compute_nb_tokens(anonymized_question),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/rephrase", response_model=RephraseResponse)
async def rephrase(request: RephraseRequest, api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner()

    try:
        rephrased, queries = await llm_runner.rephrase_and_split(
            request.question,
            request.rephrasing_prompt,
            request.queries_splitting_prompt,
        )

        return RephraseResponse(
            time=time.time() - start_time,
            rephrased_question=rephrased,
            queries=queries,
            nb_token_input=tokenizer.compute_nb_tokens(request.question),
            nb_token_output=tokenizer.compute_nb_tokens(rephrased),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/search", response_model=SearchResponse)
async def search(request: SearchRequest, api_key: str = Depends(get_api_key)):
    start_time = time.time()
    collections = AlbertCollectionHandler()
    try:
        options = request.options

        collection_ids = (
            COLLECTION_IDS
            if not options or not options.collections
            else options.collections
        )

        transformed_results = []

        for prompt in request.prompts:
            search_result = collections.search(
                prompt=prompt,
                id_collections=collection_ids,
                k=options.top_k,
                score_threshold=options.threshold,
            )

            for item in search_result.get("data", []):
                chunk_data = item["chunk"]
                metadata = chunk_data["metadata"]

                transformed_chunk = ChunkResult(
                    score=item["score"],
                    content=chunk_data["content"],
                    id_chunk=chunk_data["id"],
                    metadata=ChunkMetadata(
                        document_id=metadata["document_id"],
                        source=metadata["source"],
                        title=metadata["document_name"],
                        url=metadata["url"],
                    ),
                )
                transformed_results.append(transformed_chunk)

        return SearchResponse(
            time=time.time() - start_time,
            top_chunks=transformed_results,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, api_key: str = Depends(get_api_key)):
    start_time = time.time()
    llm_runner = LLMRunner()
    tokenizer = Tokenizer()

    try:
        if request.context_insertion_method == "chunk" and request.chunks:
            response = await llm_runner.chat_using_chunks(
                chat_history=request.chat_history,
                prompt=request.system_prompt,
                enriched_search_result_chunk=request.chunks,
            )
            sources = [
                item["chunk"]["metadata"]["url"]
                for item in request.chunks.get("data", [])
            ]
        else:
            response, rag_response = await llm_runner.chat_with_full_document(
                chat_history=request.chat_history,
                prompt=request.system_prompt,
                collection_ids=COLLECTION_IDS,
                sources=[
                    "code_du_travail",
                    "fiches_service_public",
                    "page_fiche_ministere_travail",
                    "information",
                    "contributions",
                ],
            )
            sources = [
                item["chunk"]["metadata"]["url"]
                for item in rag_response.get("data", [])
            ]

        chat_history_str = " ".join(
            [msg.get("content", "") for msg in request.chat_history]
        )

        return GenerateResponse(
            time=time.time() - start_time,
            text=response,
            nb_token_input=tokenizer.compute_nb_tokens(chat_history_str),
            nb_token_output=tokenizer.compute_nb_tokens(response),
            sources=list(set(sources)),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
