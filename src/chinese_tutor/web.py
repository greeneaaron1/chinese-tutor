from __future__ import annotations

import asyncio
import contextlib
import html
import json
import os
import shlex
import threading
from dataclasses import dataclass
from io import StringIO
from typing import Any, AsyncGenerator, Dict, Tuple

import python_multipart  # Imported so pip installs the dependency
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from dotenv import load_dotenv

from . import cli
from .elevenlabs_client import run_conversation

load_dotenv()

app = FastAPI()
app.state.active_chat = None


@dataclass
class ActiveChat:
    stop_event: threading.Event
    worker: threading.Thread


def _run_cli(args_text: str) -> Tuple[str, int]:
    argv = shlex.split(args_text) if args_text else []
    buffer = StringIO()
    exit_code = 0
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            cli.main(argv)
        except SystemExit as exc:
            code = exc.code
            if isinstance(code, int):
                exit_code = code
            elif code is None:
                exit_code = 0
            else:
                exit_code = 1
        except Exception as exc:  # noqa: BLE001
            buffer.write(f"Error: {exc}\n")
            exit_code = 1
    return buffer.getvalue(), exit_code


def _format_sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _mask_agent_id(agent_id: str | None) -> str:
    if not agent_id:
        return ""
    return f"{agent_id[:4]}...{agent_id[-4:]}" if len(agent_id) > 8 else agent_id


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
            push(
                {
                    "type": "done",
                    "exit_code": 0,
                    "conversation_id": result.metadata.get("conversation_id"),
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
  <title>Chinese Tutor Control Room</title>
  <style>
    :root {{
      --bg: #030712;
      --card: #0d1627;
      --card-strong: #0a1020;
      --accent: #22d3ee;
      --accent-2: #f97316;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --border: rgba(255,255,255,0.08);
      --shadow: 0 25px 60px rgba(0,0,0,0.35);
      --radius: 16px;
      font-family: "Space Grotesk", "Inter", "Segoe UI", "SF Pro Display", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: radial-gradient(circle at 20% 20%, #0a1628 0%, #050b16 40%, #020610 100%);
      color: var(--text);
      min-height: 100vh;
    }}
    .page {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 32px 20px 48px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(34, 211, 238, 0.12), rgba(249, 115, 22, 0.12));
      border: 1px solid var(--border);
      box-shadow: var(--shadow);
      border-radius: 20px;
      padding: 24px;
    }}
    h1 {{
      font-size: 30px;
      margin: 0 0 8px;
      letter-spacing: -0.02em;
    }}
    p.lead {{
      margin: 0 0 12px;
      color: var(--muted);
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 10px 0 16px;
    }}
    .badge {{
      padding: 8px 12px;
      background: rgba(255,255,255,0.05);
      border: 1px solid var(--border);
      border-radius: 999px;
      font-size: 12px;
      letter-spacing: 0.01em;
    }}
    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
    }}
    button {{
      border: none;
      cursor: pointer;
      padding: 12px 16px;
      border-radius: 12px;
      font-weight: 600;
      letter-spacing: 0.01em;
      transition: transform 120ms ease, box-shadow 160ms ease, background 160ms ease;
    }}
    button.primary {{
      background: linear-gradient(120deg, #22d3ee, #0ea5e9);
      color: #041019;
      box-shadow: 0 10px 30px rgba(34, 211, 238, 0.25);
    }}
    button.secondary {{
      background: rgba(255,255,255,0.06);
      color: var(--text);
      border: 1px solid var(--border);
    }}
    button:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }}
    button:hover:not(:disabled) {{
      transform: translateY(-1px);
      box-shadow: 0 12px 32px rgba(0,0,0,0.25);
    }}
    .grid {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .card h2 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: -0.01em;
    }}
    label {{
      font-size: 14px;
      color: var(--muted);
    }}
    input[type="text"] {{
      width: 100%;
      padding: 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--card-strong);
      color: var(--text);
      font-size: 15px;
    }}
    .output, .transcript {{
      background: var(--card-strong);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      font-family: "JetBrains Mono", "SFMono-Regular", "Consolas", monospace;
      white-space: pre-wrap;
      min-height: 180px;
      max-height: 360px;
      overflow: auto;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .chip {{
      padding: 8px 10px;
      background: rgba(255,255,255,0.07);
      border: 1px solid var(--border);
      border-radius: 10px;
      font-size: 13px;
      cursor: pointer;
      transition: background 140ms ease;
    }}
    .chip:hover {{
      background: rgba(255,255,255,0.12);
    }}
    .transcript-line {{
      margin: 0 0 8px;
      padding: 10px 12px;
      border-radius: 10px;
      background: rgba(255,255,255,0.04);
      border: 1px solid var(--border);
    }}
    .transcript-line .who {{
      font-weight: 700;
      color: var(--accent);
      margin-right: 6px;
    }}
    .transcript-line.agent .who {{ color: var(--accent-2); }}
    .pill-list {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 8px;
    }}
    .pill {{
      padding: 10px 12px;
      border-radius: 10px;
      background: rgba(255,255,255,0.05);
      border: 1px dashed var(--border);
      font-size: 13px;
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      .actions {{ flex-direction: column; align-items: flex-start; }}
      button {{ width: 100%; text-align: center; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Chinese Tutor Control Room</h1>
      <p class="lead">Stream live transcripts, run the CLI without a terminal, and keep your ElevenLabs Agent close at hand.</p>
      <div class="badges">
        <span class="badge">Agent ID: {html.escape(agent_id_hint) or "not configured"}</span>
        <span class="badge">AGENT_ID { "ready" if agent_id_ready else "missing" }</span>
        <span class="badge">API key { "ready" if api_key_ready else "optional / missing" }</span>
      </div>
      <div class="actions">
        <button class="primary" id="start-chat">Start Live Chat</button>
        <button class="secondary" id="stop-chat" disabled>Stop</button>
        <button class="secondary" id="clear-log">Clear log</button>
      </div>
    </section>

    <section class="grid">
      <div class="card">
        <h2>CLI runner</h2>
        <label for="args">Command (runs locally with your .env)</label>
        <form id="command-form">
          <input type="text" id="args" name="args" autocomplete="off" placeholder="chat | list --limit 5 | review --limit 3" />
          <div class="actions" style="margin-top: 12px;">
            <button type="submit" class="primary">Run command</button>
          </div>
        </form>
        <div class="chips">
          <div class="chip" data-fill="list --limit 10">list --limit 10</div>
          <div class="chip" data-fill="chat">chat (voice)</div>
          <div class="chip" data-fill="review --limit 5">review --limit 5</div>
        </div>
        <div class="pill-list">
          <div class="pill">chat: live voice session with the agent</div>
          <div class="pill">list: show recent sessions + vocab</div>
          <div class="pill">review: interactive quiz (best in terminal)</div>
        </div>
      </div>
      <div class="card">
        <h2>Live transcript</h2>
        <div id="transcript" class="transcript"></div>
      </div>
    </section>

    <section class="card">
      <h2>Output</h2>
      <div id="output" class="output"></div>
    </section>
  </div>

  <script>
    const outputEl = document.getElementById("output");
    const transcriptEl = document.getElementById("transcript");
    const startBtn = document.getElementById("start-chat");
    const stopBtn = document.getElementById("stop-chat");
    const clearBtn = document.getElementById("clear-log");
    const form = document.getElementById("command-form");
    const argsInput = document.getElementById("args");
    let chatSource = null;

    const envConfig = {json.dumps({
        "agent_ready": agent_id_ready,
        "api_ready": api_key_ready,
        "agent_hint": agent_id_hint,
    })}

    function appendOutput(line) {{
      const now = new Date().toLocaleTimeString();
      outputEl.textContent += `[${{now}}] ${{line}}\n`;
      outputEl.scrollTop = outputEl.scrollHeight;
    }}

    function appendTranscript(who, text) {{
      const div = document.createElement("div");
      div.className = "transcript-line " + (who === "Agent" ? "agent" : "user");
      div.innerHTML = `<span class="who">${{who}}:</span> ${{text}}`;
      transcriptEl.appendChild(div);
      transcriptEl.scrollTop = transcriptEl.scrollHeight;
    }}

    function setChatButtons(active) {{
      startBtn.disabled = active;
      stopBtn.disabled = !active;
    }}

    function closeChatSource() {{
      if (chatSource) {{
        chatSource.close();
        chatSource = null;
      }}
      setChatButtons(false);
    }}

    function startChat() {{
      if (!envConfig.agent_ready) {{
        appendOutput("AGENT_ID missing. Set it in your .env before chatting.");
        return;
      }}
      closeChatSource();
      setChatButtons(true);
      appendOutput("Starting live chat with agent " + (envConfig.agent_hint || ""));
      chatSource = new EventSource("/stream/chat");
      chatSource.onmessage = (event) => {{
        try {{
          const data = JSON.parse(event.data);
          handleChatEvent(data);
        }} catch (err) {{
          appendOutput("Stream parse error: " + err);
        }}
      }};
      chatSource.onerror = () => {{
        appendOutput("Stream connection dropped.");
        closeChatSource();
      }};
    }}

    function handleChatEvent(data) {{
      if (data.type === "user_transcript") {{
        appendTranscript("You", data.text);
      }} else if (data.type === "agent_response" || data.type === "agent_correction") {{
        appendTranscript("Agent", data.text);
      }} else if (data.type === "status") {{
        appendOutput(data.message || "status update");
      }} else if (data.type === "summary") {{
        appendOutput(`Summary: you spoke ${{data.user_lines}} lines; agent replied ${{data.agent_lines}} times.`);
      }} else if (data.type === "error") {{
        appendOutput("Error: " + data.message);
      }} else if (data.type === "done") {{
        appendOutput(data.exit_code === 0 ? "Chat finished." : "Chat ended with errors.");
        closeChatSource();
      }}
    }}

    async function stopChat() {{
      closeChatSource();
      try {{
        await fetch("/api/stop-chat", {{ method: "POST" }});
        appendOutput("Stop signal sent.");
      }} catch (err) {{
        appendOutput("Failed to stop chat: " + err);
      }}
    }}

    form.addEventListener("submit", async (e) => {{
      e.preventDefault();
      const args = argsInput.value.trim();
      appendOutput(`$ python -m chinese_tutor ${{args}}`);
      try {{
        const res = await fetch("/api/run", {{
          method: "POST",
          headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
          body: new URLSearchParams({{ args }}),
        }});
        if (!res.ok) {{
          appendOutput("Command failed to start: HTTP " + res.status);
          return;
        }}
        const data = await res.json();
        if (data.output) appendOutput(data.output.trim());
        appendOutput(`(exit code ${{data.exit_code}})`);
      }} catch (err) {{
        appendOutput("Command error: " + err);
      }}
    }});

    startBtn.addEventListener("click", startChat);
    stopBtn.addEventListener("click", stopChat);
    clearBtn.addEventListener("click", () => {{
      outputEl.textContent = "";
      transcriptEl.innerHTML = "";
    }});
    document.querySelectorAll(".chip").forEach((chip) => {{
      chip.addEventListener("click", () => {{
        argsInput.value = chip.dataset.fill || "";
        argsInput.focus();
      }});
    }});
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    agent_id = os.environ.get("AGENT_ID") or ""
    agent_id_hint = _mask_agent_id(agent_id)
    api_key_ready = bool(os.environ.get("ELEVENLABS_API_KEY"))
    return HTMLResponse(_render_page(agent_id_hint, bool(agent_id), api_key_ready))


@app.post("/api/run", response_class=JSONResponse)
async def run_command(args: str = Form("")) -> JSONResponse:
    output, exit_code = await asyncio.to_thread(_run_cli, args)
    return JSONResponse({"output": output, "exit_code": exit_code})


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
