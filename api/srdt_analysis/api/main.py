import json
import os
import time
from operator import itemgetter

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
    RerankRequest,
    RerankResponse,
    RerankedChunk,
    SearchRequest,
    SearchResponse,
)
from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.constants import BASE_API_URL
from srdt_analysis.llm_runner import LLMRunner
from srdt_analysis.tokenizer import Tokenizer

load_dotenv()

app = FastAPI()
api_key_header = APIKeyHeader(name="Authorization", auto_error=True)


async def get_api_key(api_key: str = Security(api_key_header)):
    if not api_key.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format. Must start with 'Bearer '",
        )
    token = api_key.replace("Bearer ", "")
    if token != os.getenv("AUTH_API_KEY"):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/")
@app.get(f"{BASE_API_URL}/")
async def root(_api_key: str = Depends(get_api_key)):
    return {"status": "ok", "path": BASE_API_URL}


@app.get(f"{BASE_API_URL}/healthz")
async def health():
    return {"health": "ok"}


@app.post(f"{BASE_API_URL}/anonymize", response_model=AnonymizeResponse)
async def anonymize(request: AnonymizeRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner(
        llm_api_token=request.model.api_key,
        llm_model=request.model.name,
        llm_url=request.model.base_url,
    )
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
async def rephrase(request: RephraseRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner(
        llm_api_token=request.model.api_key,
        llm_model=request.model.name,
        llm_url=request.model.base_url,
    )

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


@app.get(f"{BASE_API_URL}/idcc/" + "{idcc}", response_model=SearchResponse)
async def get_contributions_idcc(idcc):
    start_time = time.time()
    collections = AlbertCollectionHandler()
    try:
        idcc_chunks = collections.get_contributions_idcc(idcc)
        return SearchResponse(
            time=time.time() - start_time,
            top_chunks=idcc_chunks,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/rerank", response_model=RerankResponse)
async def rerank(request: RerankRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    collections = AlbertCollectionHandler()
    try:
        inputs = [input.content for input in request.inputs]
        res = collections.rerank(request.prompt, inputs)

        # reorder chunks based on rerank indices
        zipped = list(zip([rr["index"] for rr in res], request.inputs))
        # TODO add reranked score too
        reordered = [
            RerankedChunk(chunk=r[1]) for r in sorted(zipped, key=itemgetter(0))
        ]

        return RerankResponse(time=time.time() - start_time, results=reordered)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/search", response_model=SearchResponse)
async def search(request: SearchRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    collections = AlbertCollectionHandler()
    try:
        transformed_results = []

        for prompt in request.prompts:
            search_result = collections.search(
                prompt=prompt,
                id_collections=request.options.collections,
                k=request.options.top_K,
                score_threshold=request.options.threshold,
            )

            filtered_search_result = (
                item
                for item in search_result
                if item["score"] >= request.options.threshold
            )

            for item in filtered_search_result:
                chunk_data = item["chunk"]
                metadata = chunk_data["metadata"]

                transformed_chunk = ChunkResult(
                    score=item["score"],
                    content=chunk_data["content"],
                    id_chunk=int(chunk_data["id"]),
                    metadata=ChunkMetadata(
                        document_id=metadata["document_id"],
                        source=(
                            metadata["source"] if "source" in metadata else "internet"
                        ),
                        title=metadata["document_name"],
                        url=(
                            metadata["url"]
                            if "url" in metadata
                            else metadata["document_name"]
                        ),
                        idcc=metadata["idcc"] if "idcc" in metadata else None,
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
async def generate(request: GenerateRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner(
        llm_api_token=request.model.api_key,
        llm_model=request.model.name,
        llm_url=request.model.base_url,
    )

    try:
        response = await llm_runner.chat_with_full_document(
            request.chat_history,
            request.system_prompt,
        )

        chat_history_str = " ".join(
            [msg.get("content", "") for msg in request.chat_history]
        )

        return GenerateResponse(
            time=time.time() - start_time,
            text=response,
            nb_token_input=tokenizer.compute_nb_tokens(chat_history_str),
            nb_token_output=tokenizer.compute_nb_tokens(response),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_API_URL}/generate/stream")
async def generate_stream(
    request: GenerateRequest, _api_key: str = Depends(get_api_key)
):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner(
        llm_api_token=request.model.api_key,
        llm_model=request.model.name,
        llm_url=request.model.base_url,
    )

    try:
        chat_history_str = " ".join(
            [msg.get("content", "") for msg in request.chat_history]
        )
        nb_token_input = tokenizer.compute_nb_tokens(chat_history_str)

        async def generate_chunks():
            accumulated_response = ""
            try:
                # Send initial metadata
                initial_data = {
                    "type": "start",
                    "time": time.time() - start_time,
                    "nb_token_input": nb_token_input,
                }
                yield f"data: {json.dumps(initial_data)}\n\n"

                # Stream the response chunks
                async for chunk in llm_runner.chat_with_full_document_stream(
                    request.chat_history,
                    request.system_prompt,
                ):
                    accumulated_response += chunk
                    chunk_data = {
                        "type": "chunk",
                        "content": chunk,
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"

                # Send final metadata
                final_data = {
                    "type": "end",
                    "time": time.time() - start_time,
                    "text": accumulated_response,
                    "nb_token_input": nb_token_input,
                    "nb_token_output": tokenizer.compute_nb_tokens(
                        accumulated_response
                    ),
                }
                yield f"data: {json.dumps(final_data)}\n\n"

            except Exception:
                error_data = {
                    "type": "error",
                    "error": "An internal error occurred.",
                }
                yield f"data: {json.dumps(error_data)}\n\n"

        return StreamingResponse(
            generate_chunks(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
