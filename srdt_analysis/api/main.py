import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
from srdt_analysis.collections import Collections
from srdt_analysis.constants import BASE_API_URL, COLLECTION_IDS
from srdt_analysis.llm_runner import LLMRunner
from srdt_analysis.tokenizer import Tokenizer

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
@app.get(f"{BASE_API_URL}/")
async def root():
    return {"status": "ok", "path": BASE_API_URL}


@app.post(f"{BASE_API_URL}/anonymize", response_model=AnonymizeResponse)
async def anonymize(request: AnonymizeRequest):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner()
    try:
        anonymized = await llm_runner.anonymize(
            request.user_question, request.anonymization_prompt
        )
        return AnonymizeResponse(
            time=time.time() - start_time,
            anonymized_question=anonymized,
            nb_token_input=tokenizer.get_nb_tokens(request.user_question),
            nb_token_output=tokenizer.get_nb_tokens(anonymized),
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/rephrase", response_model=RephraseResponse)
async def rephrase(request: RephraseRequest):
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
            nb_token_input=tokenizer.get_nb_tokens(request.question),
            nb_token_output=tokenizer.get_nb_tokens(rephrased),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    start_time = time.time()
    collections = Collections()
    try:
        options = request.options

        top_k = 5 if not options or options.top_K is None else options.top_K
        threshold = (
            0.0 if not options or options.threshold is None else options.threshold
        )
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
                k=top_k,
                score_threshold=threshold,
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
async def generate(request: GenerateRequest):
    start_time = time.time()
    llm_runner = LLMRunner()
    tokenizer = Tokenizer()

    try:
        if request.context_insertion_method == "chunk" and request.chunks:
            response, rag_data = await llm_runner.chat_with_rag_data(
                chat_history=request.chat_history,
                prompt=request.system_prompt,
                data_to_send_to_llm=request.chunks,
            )
            sources = [
                item["chunk"]["metadata"]["url"] for item in rag_data.get("data", [])
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
            [msg.get("content") for msg in request.chat_history]
        )

        return GenerateResponse(
            time=time.time() - start_time,
            text=response,
            nb_token_input=tokenizer.get_nb_tokens(chat_history_str),
            nb_token_output=tokenizer.get_nb_tokens(response),
            sources=list(set(sources)),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
