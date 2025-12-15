from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from dotenv import load_dotenv

from . import extract, storage
from .elevenlabs_client import run_conversation

load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI()
app.state.active_chat = None


@dataclass
class ActiveChat:
    stop_event: threading.Event
    worker: threading.Thread


def _format_sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _persist_conversation(result) -> Tuple[int | None, List[Dict[str, str]]]:
    """
    Save the conversation transcript + vocab to SQLite.
    Returns session id and list of vocab dicts.
    """
    try:
        session_id = storage.record_session(
            started_at=result.started_at,
            ended_at=result.ended_at,
            transcript_text=result.transcript_text,
            metadata=result.metadata,
        )
        vocab_items = extract.extract_unknown_words(agent_text=result.agent_text, user_text=result.user_text)
        if vocab_items:
            storage.insert_vocab_items(vocab_items, source_session_id=session_id)
        return session_id, vocab_items
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to persist conversation: %s", exc)
        return None, []


def _start_chat_stream(
    loop: asyncio.AbstractEventLoop, agent_id: str, api_key: str | None
) -> Tuple[asyncio.Queue[Dict[str, Any]], ActiveChat]:
    active = getattr(app.state, "active_chat", None)
    if active:
        raise HTTPException(status_code=409, detail="A chat is already running. Stop it before starting a new one.")

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    stop_event = threading.Event()

    def push(event: Dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker() -> None:
        try:
            push({"type": "status", "message": "Starting live chat..."})
            result = run_conversation(
                agent_id=agent_id,
                api_key=api_key,
                event_callback=push,
                stop_event=stop_event,
                install_signal_handlers=False,
            )
            session_id, vocab_items = _persist_conversation(result)
            if session_id:
                push({"type": "status", "message": "Saved session locally."})
            if vocab_items:
                push({"type": "status", "message": f"Captured {len(vocab_items)} vocab items."})
            if vocab_items:
                push({"type": "vocab", "items": vocab_items})
            push(
                {
                    "type": "done",
                    "exit_code": 0,
                    "conversation_id": result.metadata.get("conversation_id"),
                    "session_id": session_id,
                    "vocab_count": len(vocab_items),
                    "started_at": result.started_at.isoformat(),
                    "ended_at": result.ended_at.isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            push({"type": "error", "message": str(exc)})
            push({"type": "done", "exit_code": 1})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    chat_state = ActiveChat(stop_event=stop_event, worker=thread)
    app.state.active_chat = chat_state
    return queue, chat_state


def _render_page(agent_id_hint: str, agent_id_ready: bool, api_key_ready: bool) -> str:
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Chinese Tutor</title>
  <style>
    :root {{
      --bg: #010101;
      --panel: #0b0b0f;
      --panel-2: #111118;
      --text: #f8fafc;
      --muted: #94a3b8;
      --border: rgba(255,255,255,0.18);
      --border-strong: rgba(255,255,255,0.4);
      --shadow: 0 28px 120px rgba(0,0,0,0.7);
      --radius: 18px;
      font-family: "Manrope", "Inter", "SF Pro Display", "Segoe UI", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at 18% 18%, #0f0f16 0%, #020202 50%, #000 100%);
      color: var(--text);
      min-height: 100vh;
    }}
    .page {{
      max-width: 960px;
      margin: 0 auto;
      padding: 32px 20px 60px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      padding: 20px 22px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      background: linear-gradient(135deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
      box-shadow: var(--shadow);
    }}
    .title {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-size: 12px;
      color: var(--muted);
    }}
    h1 {{
      margin: 0;
      font-size: 30px;
      letter-spacing: -0.01em;
    }}
    .lead {{
      margin: 0;
      color: var(--muted);
      max-width: 640px;
      line-height: 1.6;
    }}
    .controls {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 10px;
      min-width: 220px;
    }}
    .button-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    button {{
      cursor: pointer;
      padding: 12px 16px;
      border-radius: 12px;
      font-weight: 700;
      letter-spacing: 0.01em;
      border: 1px solid var(--border-strong);
      background: #0f0f16;
      color: var(--text);
      transition: transform 120ms ease, box-shadow 160ms ease, border-color 120ms ease, background 140ms ease;
    }}
    button.primary {{
      background: #ffffff;
      color: #000;
      border-color: #ffffff;
    }}
    button.secondary {{
      background: rgba(255,255,255,0.06);
      color: var(--text);
    }}
    button:hover:not(:disabled) {{
      transform: translateY(-1px);
      box-shadow: 0 14px 38px rgba(0,0,0,0.45);
    }}
    button:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }}
    .status {{
      font-size: 14px;
      color: var(--muted);
      text-align: right;
    }}
    .pill-row {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .pill {{
      padding: 8px 10px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.04);
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.02em;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .card h2 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: -0.01em;
    }}
    .transcript, .vocab {{
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px;
      min-height: 260px;
      max-height: 440px;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .line {{
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
    }}
    .line strong {{
      font-weight: 800;
      margin-right: 8px;
    }}
    .line.agent strong {{
      color: #fff;
    }}
    .muted {{
      color: var(--muted);
    }}
    .vocab-item {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 4px;
      padding: 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
    }}
    .vocab-top {{
      display: flex;
      gap: 10px;
      align-items: baseline;
      flex-wrap: wrap;
    }}
    .hanzi {{
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .pinyin {{
      color: var(--muted);
      font-size: 14px;
    }}
    .english {{
      font-size: 15px;
    }}
    @media (max-width: 720px) {{
      .hero {{
        flex-direction: column;
        align-items: flex-start;
      }}
      .controls {{
        width: 100%;
        align-items: flex-start;
      }}
      .status {{
        text-align: left;
      }}
      button {{
        width: auto;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="title">
        <div class="eyebrow">Chinese Tutor</div>
        <h1>Live Mandarin chat with instant transcripts.</h1>
        <p class="lead">Press start to begin speaking with your ElevenLabs Agent. Everything is saved locally so you can review the vocab any time.</p>
        <div class="pill-row">
          <span class="pill">Agent: {html.escape(agent_id_hint or "not configured")}</span>
          <span class="pill">AGENT_ID { "ready" if agent_id_ready else "missing" }</span>
          <span class="pill">API key { "ready" if api_key_ready else "optional" }</span>
        </div>
      </div>
      <div class="controls">
        <div class="button-row">
          <button class="primary" id="start-chat">Start chat</button>
          <button class="secondary" id="stop-chat" disabled>Stop</button>
        </div>
        <div class="status" id="status">Waiting to start</div>
      </div>
    </section>

    <section class="card">
      <h2>Transcript</h2>
      <div id="transcript" class="transcript"></div>
    </section>

    <section class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
        <h2 style="margin:0;">Vocabulary to review</h2>
        <button class="secondary" id="refresh-vocab">Refresh list</button>
      </div>
      <div id="vocab" class="vocab"></div>
    </section>
  </div>

  <script>
    const transcriptEl = document.getElementById("transcript");
    const vocabEl = document.getElementById("vocab");
    const startBtn = document.getElementById("start-chat");
    const stopBtn = document.getElementById("stop-chat");
    const statusEl = document.getElementById("status");
    const refreshBtn = document.getElementById("refresh-vocab");
    let chatSource = null;

    const envConfig = {json.dumps({
        "agent_ready": agent_id_ready,
        "api_ready": api_key_ready,
        "agent_hint": agent_id_hint,
    })}

    function appendTranscript(who, text) {{
      const div = document.createElement("div");
      div.className = "line " + (who === "Agent" ? "agent" : "user");
      const whoEl = document.createElement("strong");
      whoEl.textContent = `${{who}}:`;
      const textEl = document.createElement("span");
      textEl.textContent = ` ${{text}}`;
      div.append(whoEl, textEl);
      transcriptEl.appendChild(div);
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    }}

    function setChatButtons(active) {{
      startBtn.disabled = active;
      stopBtn.disabled = !active;
    }}

    function setStatus(text) {{
      statusEl.textContent = text;
    }}

    function closeChatSource() {{
      if (chatSource) {{
        chatSource.close();
        chatSource = null;
      }}
      setChatButtons(false);
      setStatus("Ready when you are.");
    }}

    function startChat() {{
      if (!envConfig.agent_ready) {{
        setStatus("AGENT_ID missing. Set it in your .env before chatting.");
        return;
      }}
      closeChatSource();
      setChatButtons(true);
      transcriptEl.innerHTML = "";
      setStatus("Connecting to your agent...");
      chatSource = new EventSource("/stream/chat");
      chatSource.onmessage = (event) => {{
        try {{
          const data = JSON.parse(event.data);
          handleChatEvent(data);
        }} catch (err) {{
          setStatus("Stream parse error: " + err);
        }}
      }};
      chatSource.onerror = () => {{
        setStatus("Stream connection dropped.");
        closeChatSource();
      }};
    }}

    function handleChatEvent(data) {{
      if (data.type === "user_transcript") {{
        appendTranscript("You", data.text);
      }} else if (data.type === "agent_response" || data.type === "agent_correction") {{
        appendTranscript("Agent", data.text);
      }} else if (data.type === "status") {{
        setStatus(data.message || "Status update");
      }} else if (data.type === "vocab" && Array.isArray(data.items)) {{
        renderVocab(data.items, true);
      }} else if (data.type === "error") {{
        setStatus("Error: " + data.message);
      }} else if (data.type === "done") {{
        if (data.exit_code === 0) {{
          setStatus("Chat saved" + (data.vocab_count ? ` with ${{data.vocab_count}} vocab items.` : "."));
        }} else {{
          setStatus("Chat ended with errors.");
        }}
        fetchVocab();
        closeChatSource();
      }}
    }}

    async function stopChat() {{
      closeChatSource();
      try {{
        await fetch("/api/stop-chat", {{ method: "POST" }});
        setStatus("Stop signal sent.");
      }} catch (err) {{
        setStatus("Failed to stop chat: " + err);
      }}
    }}

    function renderVocab(items, prepend = false) {{
      if (!Array.isArray(items) || !items.length) {{
        vocabEl.innerHTML = '<div class="muted">No vocab saved yet. Finish a chat to capture new words.</div>';
        return;
      }}
      if (!prepend) {{
        vocabEl.innerHTML = "";
      }} else if (!vocabEl.children.length) {{
        vocabEl.innerHTML = "";
      }}
      const fragment = document.createDocumentFragment();
      items.forEach((item) => {{
        const wrapper = document.createElement("div");
        wrapper.className = "vocab-item";

        const top = document.createElement("div");
        top.className = "vocab-top";

        const hanzi = document.createElement("span");
        hanzi.className = "hanzi";
        hanzi.textContent = item.chinese || "—";
        top.appendChild(hanzi);

        if (item.pinyin) {{
          const pinyin = document.createElement("span");
          pinyin.className = "pinyin";
          pinyin.textContent = item.pinyin;
          top.appendChild(pinyin);
        }}

        const english = document.createElement("div");
        english.className = "english";
        english.textContent = item.english || "";

        wrapper.append(top, english);

        if (item.example) {{
          const example = document.createElement("div");
          example.className = "muted";
          example.textContent = item.example;
          wrapper.appendChild(example);
        }}

        fragment.appendChild(wrapper);
      }});
      if (prepend && vocabEl.children.length) {{
        vocabEl.insertBefore(fragment, vocabEl.firstChild);
      }} else {{
        vocabEl.appendChild(fragment);
      }}
    }}

    async function fetchVocab() {{
      try {{
        const res = await fetch("/api/vocab?limit=80");
        const data = await res.json();
        renderVocab(data.items || []);
      }} catch (err) {{
        vocabEl.innerHTML = '<div class="muted">Unable to load vocab right now.</div>';
      }}
    }}

    startBtn.addEventListener("click", startChat);
    stopBtn.addEventListener("click", stopChat);
    refreshBtn.addEventListener("click", fetchVocab);
    fetchVocab();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    agent_id = os.environ.get("AGENT_ID") or ""
    agent_id_hint = f"{agent_id[:4]}...{agent_id[-4:]}" if len(agent_id) > 8 else agent_id
    api_key_ready = bool(os.environ.get("ELEVENLABS_API_KEY"))
    return HTMLResponse(_render_page(agent_id_hint, bool(agent_id), api_key_ready))


@app.get("/api/vocab", response_class=JSONResponse)
async def list_vocab(limit: int = 80) -> JSONResponse:
    rows = await asyncio.to_thread(storage.list_vocab, limit)
    items = [
        {
            "id": row["id"],
            "english": row["english"],
            "chinese": row["chinese"],
            "pinyin": row["pinyin"],
            "example": row["example"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
    return JSONResponse({"items": items})


@app.get("/stream/chat")
async def stream_chat() -> StreamingResponse:
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id:
        raise HTTPException(status_code=400, detail="AGENT_ID is required. Set it in your environment or .env file.")
    loop = asyncio.get_running_loop()
    queue, chat_state = _start_chat_stream(loop, agent_id, os.environ.get("ELEVENLABS_API_KEY"))

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                event = await queue.get()
                yield _format_sse(event)
                if event.get("type") == "done":
                    break
        finally:
            chat_state.stop_event.set()
            chat_state.worker.join(timeout=2)
            if getattr(app.state, "active_chat", None) is chat_state:
                app.state.active_chat = None

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/stop-chat", response_class=JSONResponse)
async def stop_chat() -> JSONResponse:
    active: ActiveChat | None = getattr(app.state, "active_chat", None)
    if not active:
        return JSONResponse({"stopped": False, "reason": "no-active-chat"})
    active.stop_event.set()
    return JSONResponse({"stopped": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("chinese_tutor.web:app", host="127.0.0.1", port=3000, reload=False)
