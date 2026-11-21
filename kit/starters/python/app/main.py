import asyncio
import hashlib
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.concurrency import run_in_threadpool
from .contracts import DocumentOutput, TransformInput, TransformOutput, utf16_length, validate_contract

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KIT_")
    cors_origins: str = ""
    max_upload_bytes: int = 1_000_000
    worker_concurrency: int = 2
    revision: str = "development"

settings = Settings()
if not 1 <= settings.worker_concurrency <= 8 or not 1 <= settings.max_upload_bytes <= 10_000_000:
    raise ValueError("Invalid worker/upload limits")
logger = logging.getLogger("hackathon-kit")
JS_WS = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.workers = asyncio.Semaphore(settings.worker_concurrency)
    yield

app = FastAPI(title="Hackathon Kit Python", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[s.strip() for s in settings.cors_origins.split(",") if s.strip()], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Request-ID"])

def error_response(request: Request, code: str, message: str, status: int):
    body = {"error": {"code": code, "message": message, "requestId": getattr(request.state, "request_id", str(uuid.uuid4())), "retryable": status == 503}}
    validate_contract("ApiError", body)
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.error("request_failed id=%s", request.state.request_id)
        response = error_response(request, "INTERNAL_ERROR", "The request failed.", 500)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info("request id=%s method=%s path=%s status=%s duration_ms=%.1f", request.state.request_id, request.method, request.url.path, response.status_code, (time.monotonic()-start)*1000)
    return response

@app.exception_handler(RequestValidationError)
async def invalid_request(request, _error):
    return error_response(request, "INVALID_INPUT", "Invalid input. Check the request schema.", 422)

@app.get("/health")
def health():
    return {"status": "ok", "service": "python", "revision": settings.revision}

@app.get("/ready")
def ready():
    return {"status": "ready", "contractSchema": "loaded", "ocr": "separate optional worker", "revision": settings.revision}

def transform(payload: dict):
    text = payload["text"]
    if payload.get("operation", "normalize") == "normalize":
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"[\t ]+", " ", text)
        text = "\n".join(line.strip(JS_WS) for line in text.split("\n")).strip(JS_WS)
    words = len(re.split(f"[{JS_WS}]+", text.strip(JS_WS))) if text.strip(JS_WS) else 0
    return validate_contract("TransformResult", {"text": text, "words": words, "characters": utf16_length(text), "mode": "local"})

@app.post("/transform", response_model=TransformOutput)
async def transform_route(payload: TransformInput, request: Request):
    async with request.app.state.workers:
        return await run_in_threadpool(transform, payload.root)

def normalize_upload(data: bytes, filename: str):
    original = data.decode("utf-8-sig", errors="strict")
    text = re.sub(r"\r\n?", "\n", original)
    digest = hashlib.sha256(data).hexdigest()
    document_id = "doc-" + digest[:24]
    segments = []
    last_index = 0
    offset = 0
    for match in re.finditer(r"[^\n]+(?:\n|$)", text):
        offset += utf16_length(text[last_index:match.start()])
        start = offset
        offset += utf16_length(match.group(0))
        segments.append({"id": f"{document_id}:s{len(segments)}", "start": start, "end": offset})
        last_index = match.end()
    return validate_contract("Document", {"id": document_id, "filename": filename, "mimeType": "text/markdown" if filename.lower().endswith(".md") else "text/plain", "hash": digest, "text": text, "segments": segments, "metadata": {"mode": "local", "offsetEncoding": "utf-16", "hashAlgorithm": "sha256", "warnings": [] if text.strip() else ["EMPTY_DOCUMENT"]}})

@app.post("/documents/text", response_model=DocumentOutput)
async def upload_text(request: Request, filename: Annotated[str, Query(min_length=1, max_length=255)] = "upload.txt"):
    # Raw streaming body enforces the bound before accumulation; no multipart spool.
    if request.headers.get("content-type", "").split(";")[0] not in ("text/plain", "text/markdown", "application/octet-stream"):
        return error_response(request, "UNSUPPORTED_TYPE", "Send UTF-8 text as the raw request body.", 415)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_upload_bytes:
                return error_response(request, "FILE_TOO_LARGE", "Upload exceeds byte limit.", 413)
        except ValueError:
            return error_response(request, "INVALID_INPUT", "Invalid Content-Length.", 400)
    body = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > settings.max_upload_bytes:
                    return error_response(request, "FILE_TOO_LARGE", "Upload exceeds byte limit.", 413)
        async with request.app.state.workers:
            return await run_in_threadpool(normalize_upload, bytes(body), filename)
    except UnicodeDecodeError:
        return error_response(request, "INVALID_ENCODING", "Upload must contain valid UTF-8.", 422)
    except TimeoutError:
        return error_response(request, "UPLOAD_TIMEOUT", "Upload timed out.", 408)
