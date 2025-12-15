# chinese-tutor

Local-first Mandarin practice with your ElevenLabs Agent. Start a voice chat, read the transcript, and keep a clean list of vocab to review later.

## Official docs (browsed)
- ElevenLabs Agents overview: https://elevenlabs.io/docs/agents-platform/overview
- ElevenLabs Python SDK (Conversation helper + DefaultAudioInterface): https://elevenlabs.io/docs/agents-platform/libraries/python
- ElevenLabs conversational Python example repo: https://github.com/elevenlabs/elevenlabs-examples/tree/main/examples/conversational-ai/python

## Requirements
- Python 3.11+
- Microphone + speakers/headphones
- ElevenLabs Agent ID (`AGENT_ID`) and API key (`ELEVENLABS_API_KEY`) for private agents

Audio dependencies (PortAudio) are needed for the SDK’s `DefaultAudioInterface` (PyAudio extra):
- macOS: `brew install portaudio`
- Debian/Ubuntu: `sudo apt-get update && sudo apt-get install libportaudio2 libportaudiocpp0 portaudio19-dev libasound-dev libsndfile1-dev -y`

## Setup
```bash
python -m venv .venv
source .venv/bin/activate  # or Scripts\\activate on Windows
pip install -e .           # installs dependencies and makes chinese_tutor importable

cp .env.example .env
# edit .env to fill ELEVENLABS_API_KEY and AGENT_ID
```

**Important:** The `pip install -e .` step is required for both CLI and web app usage. It installs the package in editable mode so Python can import the `chinese_tutor` module.

## Usage (CLI)
All commands run locally; data is stored in SQLite at `~/.chinese-tutor/chinese_tutor.db` (override with `CHINESE_TUTOR_DB_PATH`).

```bash
# Live voice chat with your agent (Ctrl+C to end)
python -m chinese_tutor chat

# Show the saved vocab list (newest first)
python -m chinese_tutor list --limit 20

# Make targets (optional)
make chat
make list
make web    # Start web UI server
```

## Web UI (streaming)
**Prerequisites:** complete the setup steps above, especially `pip install -e .` so the `chinese_tutor` module is importable.

- Launch: `uvicorn chinese_tutor.web:app --host 0.0.0.0 --port 3000`
  - Or use the Makefile: `make web` (runs on port 3000)
- Features: start/stop a live chat, watch the transcript stream, and see all captured vocab (Chinese, pinyin, English, example) in a single dark view.
- Requirements: `.env` with `AGENT_ID` (and optionally `ELEVENLABS_API_KEY` for private agents) plus working mic/speakers on the machine running the server.

## What happens during `chat`
- Uses `elevenlabs.conversational_ai.Conversation` with `DefaultAudioInterface` to stream mic audio to your Agent and play replies.
- Prints transcripts (user + agent) as they stream.
- On exit, saves a session record to SQLite with timestamps, transcript, and the ElevenLabs conversation ID.
- Extracts vocab candidates:
  - Primary: parses any agent “快速复习一下…” vocab check lines like `1) 超市 (chāoshì) — grocery store — 例句：…`
  - Fallback: captures English phrases you said mid-sentence.
  - Stored fields: english, chinese, pinyin, example.

## Data layout
SQLite lives at `~/.chinese-tutor/chinese_tutor.db` (or `CHINESE_TUTOR_DB_PATH`):
- `sessions(id, started_at, ended_at, transcript_text, metadata_json)`
- `vocab(id, created_at, source_session_id, english, chinese, pinyin, example, seen_count, last_seen_at, last_result)`

## Troubleshooting
- **ModuleNotFoundError: No module named 'chinese_tutor'**: This means the package isn't installed. Run `pip install -e .` from the project root with your virtual environment activated. This installs the package in editable mode so Python can import it.
- Mic/speaker errors: confirm PortAudio/PyAudio are installed (see above) and the devices are available. The SDK’s `DefaultAudioInterface` relies on system defaults.
- Auth: `AGENT_ID` is required. `ELEVENLABS_API_KEY` is required only for private agents.
- Database path: set `CHINESE_TUTOR_DB_PATH` to move the DB elsewhere.
