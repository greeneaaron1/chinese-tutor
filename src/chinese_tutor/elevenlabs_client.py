from __future__ import annotations

import logging
import queue
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

logger = logging.getLogger(__name__)


@dataclass
class ConversationResult:
    started_at: datetime
    ended_at: datetime
    transcript_text: str
    metadata: Dict[str, str]
    user_text: str
    agent_text: str


class HalfDuplexAudioInterface(DefaultAudioInterface):
    """
    Avoid sending the agent's own playback back to the microphone stream.

    The default interface streams mic input continuously. When the speaker audio
    is loud enough to leak into the mic, the agent transcribes itself and treats
    it as user speech. This wrapper temporarily mutes microphone frames while
    agent audio is being written to the output stream (plus a small padding) so
    that only true user speech is forwarded to the conversation.
    """

    SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM
    SAMPLE_RATE = 16000
    MUTE_PADDING_SECONDS = 0.2

    def __init__(self) -> None:
        super().__init__()
        self._mute_until = 0.0
        self._mute_lock = threading.Lock()
        self._user_input_callback: Optional[Callable[[bytes], None]] = None

    def start(self, input_callback):
        self._mute_until = 0.0
        self._user_input_callback = input_callback
        return super().start(input_callback)

    def _extend_mute(self, duration_seconds: float) -> None:
        with self._mute_lock:
            self._mute_until = max(self._mute_until, time.monotonic() + duration_seconds)

    def _input_allowed(self) -> bool:
        with self._mute_lock:
            return time.monotonic() >= self._mute_until

    def _output_thread(self):
        while not self.should_stop.is_set():
            try:
                audio = self.output_queue.get(timeout=0.25)
                duration_seconds = len(audio) / (self.SAMPLE_WIDTH_BYTES * self.SAMPLE_RATE)
                # Keep the mic muted while playback occurs and for a short tail period.
                self._extend_mute(duration_seconds + self.MUTE_PADDING_SECONDS)
                self.out_stream.write(audio)
            except queue.Empty:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("Audio output error: %s", exc)

    def _in_callback(self, in_data, frame_count, time_info, status):
        if self._user_input_callback and self._input_allowed():
            self._user_input_callback(in_data)
        return (None, self.pyaudio.paContinue)


def _safe_emit(callback: Optional[Callable[[Dict[str, str]], None]], event: Dict[str, str]) -> None:
    if not callback:
        return
    try:
        callback(event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Streaming event failed to emit: %s", exc)


def _watch_stop_event(
    stop_event: threading.Event,
    conversation: Conversation,
    event_callback: Optional[Callable[[Dict[str, str]], None]],
) -> None:
    stop_event.wait()
    if not stop_event.is_set():
        return
    _safe_emit(event_callback, {"type": "status", "message": "Stopping conversation..."})
    try:
        conversation.end_session()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Conversation end_session failed: %s", exc)


def run_conversation(
    agent_id: str,
    api_key: Optional[str],
    event_callback: Optional[Callable[[Dict[str, str]], None]] = None,
    stop_event: Optional[threading.Event] = None,
    install_signal_handlers: bool = True,
) -> ConversationResult:
    """
    Start a live conversation with the ElevenLabs Agent and return transcript data.
    When provided, event_callback will receive streaming events:
    - {"type": "user_transcript"|"agent_response"|"agent_correction", "text": str, "timestamp": iso8601}
    - {"type": "status", "message": str}
    - {"type": "summary", "user_lines": str(int), "agent_lines": str(int)}

    stop_event (if passed) can be set to end the conversation early.
    install_signal_handlers controls whether SIGINT (Ctrl+C) is captured to stop the session.
    """
    user_lines: List[str] = []
    agent_lines: List[str] = []
    transcript_lines: List[str] = []

    def on_user_transcript(transcript: str) -> None:
        logger.info("You: %s", transcript)
        transcript_lines.append(f"User: {transcript}")
        user_lines.append(transcript)
        _safe_emit(
            event_callback,
            {"type": "user_transcript", "text": transcript, "timestamp": datetime.now().isoformat()},
        )

    def on_agent_response(response: str) -> None:
        logger.info("Agent: %s", response)
        transcript_lines.append(f"Agent: {response}")
        agent_lines.append(response)
        _safe_emit(
            event_callback,
            {"type": "agent_response", "text": response, "timestamp": datetime.now().isoformat()},
        )

    def on_agent_correction(original: str, corrected: str) -> None:
        logger.info("Agent corrected: %s -> %s", original, corrected)
        transcript_lines.append(f"Agent: {corrected}")
        agent_lines.append(corrected)
        _safe_emit(
            event_callback,
            {"type": "agent_correction", "text": corrected, "timestamp": datetime.now().isoformat()},
        )

    try:
        audio_interface = HalfDuplexAudioInterface()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Could not initialize audio. Make sure PyAudio/PortAudio is installed and microphones/speakers are available."
        ) from exc

    client = ElevenLabs(api_key=api_key)
    conversation = Conversation(
        client,
        agent_id,
        requires_auth=bool(api_key),
        audio_interface=audio_interface,
        callback_agent_response=on_agent_response,
        callback_agent_response_correction=on_agent_correction,
        callback_user_transcript=on_user_transcript,
    )

    _safe_emit(
        event_callback,
        {"type": "status", "message": f"Connecting to ElevenLabs Agent {agent_id}"},
    )

    def _handle_sigint(sig: int, frame) -> None:  # noqa: ANN001
        logger.info("Stopping conversation...")
        conversation.end_session()

    if install_signal_handlers:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, _handle_sigint)
        else:
            logger.debug("Skipping SIGINT handler install because we're not on the main thread.")

    logger.info("Connecting to ElevenLabs Agent %s ...", agent_id)
    started_at = datetime.now()
    conversation.start_session()

    stopper_thread: Optional[threading.Thread] = None
    if stop_event is not None:
        stopper_thread = threading.Thread(
            target=_watch_stop_event, args=(stop_event, conversation, event_callback), daemon=True
        )
        stopper_thread.start()

    _safe_emit(event_callback, {"type": "status", "message": "Session started"})
    try:
        conversation_id = conversation.wait_for_session_end()
    except KeyboardInterrupt:
        conversation.end_session()
        conversation_id = conversation.wait_for_session_end()
    ended_at = datetime.now()

    if stop_event is not None and stopper_thread is not None:
        stop_event.set()
        stopper_thread.join(timeout=1)

    metadata = {"conversation_id": conversation_id}
    transcript_text = "\n".join(transcript_lines)
    _safe_emit(
        event_callback,
        {
            "type": "summary",
            "user_lines": str(len(user_lines)),
            "agent_lines": str(len(agent_lines)),
            "conversation_id": conversation_id,
        },
    )
    _safe_emit(event_callback, {"type": "status", "message": "Conversation finished"})
    return ConversationResult(
        started_at=started_at,
        ended_at=ended_at,
        transcript_text=transcript_text,
        metadata=metadata,
        user_text="\n".join(user_lines),
        agent_text="\n".join(agent_lines),
    )
