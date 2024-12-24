import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from srdt_analysis.api.schemas import (
    AnonymizeRequest,
    AnonymizeResponse,
)
from srdt_analysis.constants import BASE_API_URL
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
