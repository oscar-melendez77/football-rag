import os
import threading
import time
from collections import OrderedDict, defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ask_assistant import Assistant

PAGE = Path(__file__).parent / "static" / "index.html"
RATE_LIMIT_PER_MINUTE = int(os.getenv("DEMO_RATE_LIMIT_PER_MINUTE", "5"))
DAILY_LLM_LIMIT = int(os.getenv("DEMO_DAILY_LLM_LIMIT", "200"))
CACHE_SECONDS = int(os.getenv("DEMO_CACHE_SECONDS", "3600"))
CACHE_MAX_ITEMS = 200

state = {}
lock = threading.Lock()
recent_requests = defaultdict(deque)
cache = OrderedDict()
daily = {"date": None, "llm_calls": 0}


@asynccontextmanager
async def lifespan(app):
    state["assistant"] = Assistant()
    yield
    state.clear()


app = FastAPI(title="Football RAG Assistant", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=300)


def client_id(request):
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(visitor):
    now = time.time()
    with lock:
        window = recent_requests[visitor]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Too many questions. Please wait a minute and try again.")
        window.append(now)


def cache_key(question):
    return " ".join(question.lower().split())


def get_cached(key):
    with lock:
        item = cache.get(key)
        if item and time.time() - item["at"] < CACHE_SECONDS:
            cache.move_to_end(key)
            return item["result"]
        cache.pop(key, None)
        return None


def store_cached(key, result):
    with lock:
        cache[key] = {"at": time.time(), "result": result}
        cache.move_to_end(key)
        while len(cache) > CACHE_MAX_ITEMS:
            cache.popitem(last=False)


def reserve_llm_call():
    today = datetime.now(timezone.utc).date().isoformat()
    with lock:
        if daily["date"] != today:
            daily["date"], daily["llm_calls"] = today, 0
        if daily["llm_calls"] >= DAILY_LLM_LIMIT:
            raise HTTPException(status_code=429, detail="The daily demo limit was reached. Please try again tomorrow.")
        daily["llm_calls"] += 1


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": "assistant" in state,
        "llm_calls_today": daily["llm_calls"],
        "daily_llm_limit": DAILY_LLM_LIMIT,
        "cached_answers": len(cache),
    }


@app.post("/ask")
def ask(body: AskRequest, request: Request):
    check_rate_limit(client_id(request))
    question = body.question.strip()
    key = cache_key(question)

    cached = get_cached(key)
    if cached:
        return {**cached, "cached": True}

    reserve_llm_call()
    try:
        result = state["assistant"].ask(question)
    except RuntimeError:
        raise HTTPException(status_code=502, detail="The answer service is temporarily unavailable. Please try again later.")
    store_cached(key, result)
    return {**result, "cached": False}


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE.read_text(encoding="utf-8")