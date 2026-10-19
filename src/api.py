from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ask_assistant import Assistant

PAGE = Path(__file__).parent / "static" / "index.html"
state = {}


@asynccontextmanager
async def lifespan(app):
    state["assistant"] = Assistant()
    yield
    state.clear()


app = FastAPI(title="Football RAG Assistant", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=300)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": "assistant" in state}


@app.post("/ask")
def ask(request: AskRequest):
    try:
        return state["assistant"].ask(request.question.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE.read_text(encoding="utf-8")