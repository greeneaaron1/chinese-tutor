# chinese-tutor

Minimal, local-first CLI for daily Mandarin conversation with an existing ElevenLabs Agent plus a tiny vocab review loop.

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
pip install -e .           # installs elevenlabs[pyaudio] + python-dotenv

cp .env.example .env
# edit .env to fill ELEVENLABS_API_KEY and AGENT_ID
```

## Usage
All commands run locally; data is stored in SQLite at `~/.chinese-tutor/chinese_tutor.db` (override with `CHINESE_TUTOR_DB_PATH`).

```bash
# Live voice chat with your agent (Ctrl+C to end)
python -m chinese_tutor chat

# Quick vocab quiz
python -m chinese_tutor review

# Show recent sessions + vocab
python -m chinese_tutor list

# Make targets (optional)
make chat
make review
make list
```

## What happens during `chat`
- Uses `elevenlabs.conversational_ai.Conversation` with `DefaultAudioInterface` to stream mic audio to your Agent and play replies.
- Prints transcripts (user + agent) as they stream.
- On exit, saves a session record to SQLite with timestamps, transcript, and the ElevenLabs conversation ID.
- Extracts vocab candidates:
  - Primary: parses any agent “快速复习一下…” vocab check lines like `1) 超市 (chāoshì) — grocery store — 例句：…`
  - Fallback: captures English phrases you said mid-sentence.
  - Stored fields: english, chinese, pinyin, example, plus review stats.

## Review logic (MVP)
- Each vocab row tracks `seen_count`, `last_seen_at`, `last_result` (`pass`/`fail`).
- Review prefers items you failed most recently, otherwise least recently seen.
- Prompts are minimal: press `p` to pass, `f` to mark fail, `q` to stop.

## Data layout
SQLite lives at `~/.chinese-tutor/chinese_tutor.db` (or `CHINESE_TUTOR_DB_PATH`):
- `sessions(id, started_at, ended_at, transcript_text, metadata_json)`
- `vocab(id, created_at, source_session_id, english, chinese, pinyin, example, seen_count, last_seen_at, last_result)`

## Troubleshooting
- Mic/speaker errors: confirm PortAudio/PyAudio are installed (see above) and the devices are available. The SDK’s `DefaultAudioInterface` relies on system defaults.
- Auth: `AGENT_ID` is required. `ELEVENLABS_API_KEY` is required only for private agents.
- Database path: set `CHINESE_TUTOR_DB_PATH` to move the DB elsewhere.
