import json
import os
import time
import traceback
from operator import itemgetter
from typing import List

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from tenacity import RetryError

from srdt_analysis.anonymiser import anonymise_spacy
from srdt_analysis.api.schemas import (
    AnonymizeRequest,
    AnonymizeResponse,
    ChunkResult,
    GenerateRequest,
    GenerateResponse,
    RephraseRequest,
    RephraseResponse,
    RerankedChunk,
    RerankRequest,
    RerankResponse,
    RetrieveRequest,
    RetrieveResponse,
    SearchRequest,
    SearchResponse,
)
from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.constants import BASE_API_URL, CHUNK_INDEX
from srdt_analysis.corpus import getChunksByIdcc, getDocsContent
from srdt_analysis.elastic_handler import ElasticIndicesHandler
from srdt_analysis.exceptions import SRDTException
from srdt_analysis.llm_runner import LLMRunner
from srdt_analysis.logger import Logger
from srdt_analysis.tokenizer import Tokenizer
from srdt_analysis.url_cleaner import clean_urls

load_dotenv()

app = FastAPI()
api_key_header = APIKeyHeader(name="Authorization", auto_error=True)
logger = Logger("API")


@app.exception_handler(Exception)
async def srdt_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, SRDTException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": type(exc).__name__,
                "message": str(exc),
                "service": exc.service,
            },
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Error",
                "message": f"Unhandled error: {str(exc)}",
            },
        )


@app.exception_handler(RetryError)
async def retry_error_handler(request: Request, exc: RetryError) -> JSONResponse:
    cause = exc.last_attempt.exception()
    if isinstance(cause, SRDTException):
        return await srdt_exception_handler(request, cause)
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Error",
                "message": f"Service failed after retries: {str(cause)}",
            },
        )


es_ok = ElasticIndicesHandler().check_connection()
if es_ok:
    logger.info("Elastic connection OK")
else:
    logger.error("Elastic connection KO")


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
async def anonymize(request: AnonymizeRequest):
    start_time = time.time()
    tokenizer = Tokenizer()
    anonymized_question = anonymise_spacy(request.user_question)
    return AnonymizeResponse(
        time=time.time() - start_time,
        anonymized_question=anonymized_question,
        nb_token_input=tokenizer.compute_nb_tokens(request.user_question),
        nb_token_output=tokenizer.compute_nb_tokens(anonymized_question),
    )


@app.post(f"{BASE_API_URL}/rephrase", response_model=RephraseResponse)
async def rephrase(request: RephraseRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner(
        llm_api_token=request.model.api_key,
        llm_model=request.model.name,
        llm_url=request.model.base_url,
    )

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


@app.get(f"{BASE_API_URL}/idcc/" + "{idcc}", response_model=SearchResponse)
async def get_contributions_idcc(idcc: str, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    idcc_chunks = getChunksByIdcc(idcc)
    return SearchResponse(
        time=time.time() - start_time,
        top_chunks=idcc_chunks,
    )


@app.post(f"{BASE_API_URL}/docs/retrieve", response_model=RetrieveResponse)
async def get_docs(request: RetrieveRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    ids = request.ids
    contents = getDocsContent(ids)
    return RetrieveResponse(time=time.time() - start_time, contents=contents)


@app.post(f"{BASE_API_URL}/rerank", response_model=RerankResponse)
async def rerank(request: RerankRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    collections = AlbertCollectionHandler()

    # Albert seemd to be using bge-reranker-v2-m3 that is limited to 512, Albert silently fails if we don't respect this limit / not documented
    # inputs = [tokenizer.take_n(input.content, 512) for input in request.inputs]
    # TODO dunno why but hard limit seemd to perform better than token selection, we should build chunks based on this limitation if it actually exists
    inputs = [input.content[:8192] for input in request.inputs]
    res = collections.rerank(request.prompt, inputs)

    # reorder results based on rerank indices to map chunks and results
    sorted_res = sorted(res, key=lambda res: res["index"])
    zipped = list(
        zip(
            [rr["index"] for rr in sorted_res],
            [rr["relevance_score"] for rr in sorted_res],
            request.inputs,
        )
    )

    # reorder using rerank score
    reordered = [
        RerankedChunk(chunk=r[2], rerank_score=r[1])
        for r in sorted(zipped, key=itemgetter(1), reverse=True)
    ]

    return RerankResponse(time=time.time() - start_time, results=reordered)


@app.post(f"{BASE_API_URL}/search", response_model=SearchResponse)
async def search(request: SearchRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    es = ElasticIndicesHandler()

    transformed_results: List[ChunkResult] = []

    for prompt in request.prompts:
        search_result = es.search(
            index_name=CHUNK_INDEX,
            prompt=prompt,
            k=request.options.top_K,
            hybrid=request.options.hybrid or False,
            sources=request.options.collections,
        )

        transformed_results = [
            item for item in search_result if item.score >= request.options.threshold
        ]

    return SearchResponse(
        time=time.time() - start_time,
        top_chunks=transformed_results,
    )


@app.post(f"{BASE_API_URL}/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, _api_key: str = Depends(get_api_key)):
    start_time = time.time()
    tokenizer = Tokenizer()
    llm_runner = LLMRunner(
        llm_api_token=request.model.api_key,
        llm_model=request.model.name,
        llm_url=request.model.base_url,
    )

    response = await llm_runner.chat_with_full_document(
        request.chat_history,
        request.system_prompt,
    )

    response = clean_urls(response)

    chat_history_str = " ".join(
        [msg.get("content", "") for msg in request.chat_history]
    )

    return GenerateResponse(
        time=time.time() - start_time,
        text=response,
        nb_token_input=tokenizer.compute_nb_tokens(chat_history_str),
        nb_token_output=tokenizer.compute_nb_tokens(response),
    )


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

            cleaned_accumulated = clean_urls(accumulated_response)
            # Send final metadata
            final_data = {
                "type": "end",
                "time": time.time() - start_time,
                "text": cleaned_accumulated,
                "nb_token_input": nb_token_input,
                "nb_token_output": tokenizer.compute_nb_tokens(cleaned_accumulated),
            }
            yield f"data: {json.dumps(final_data)}\n\n"

        except Exception as e:
            logger.error(
                f"Stream generation error: {str(e)}, traceback: {traceback.format_exc()}"
            )
            error_data = {
                "type": "error",
                "error": "Stream generation failed",
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
