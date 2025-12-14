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


def run_conversation(agent_id: str, api_key: Optional[str]) -> ConversationResult:
    """
    Start a live conversation with the ElevenLabs Agent and return transcript data.
    """
    user_lines: List[str] = []
    agent_lines: List[str] = []
    transcript_lines: List[str] = []

    def on_user_transcript(transcript: str) -> None:
        logger.info("You: %s", transcript)
        transcript_lines.append(f"User: {transcript}")
        user_lines.append(transcript)

    def on_agent_response(response: str) -> None:
        logger.info("Agent: %s", response)
        transcript_lines.append(f"Agent: {response}")
        agent_lines.append(response)

    def on_agent_correction(original: str, corrected: str) -> None:
        logger.info("Agent corrected: %s -> %s", original, corrected)
        transcript_lines.append(f"Agent: {corrected}")
        agent_lines.append(corrected)

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

    def _handle_sigint(sig: int, frame) -> None:  # noqa: ANN001
        logger.info("Stopping conversation...")
        conversation.end_session()

    signal.signal(signal.SIGINT, _handle_sigint)

    logger.info("Connecting to ElevenLabs Agent %s ...", agent_id)
    started_at = datetime.now()
    conversation.start_session()

    try:
        conversation_id = conversation.wait_for_session_end()
    except KeyboardInterrupt:
        conversation.end_session()
        conversation_id = conversation.wait_for_session_end()
    ended_at = datetime.now()

    metadata = {"conversation_id": conversation_id}
    transcript_text = "\n".join(transcript_lines)
    return ConversationResult(
        started_at=started_at,
        ended_at=ended_at,
        transcript_text=transcript_text,
        metadata=metadata,
        user_text="\n".join(user_lines),
        agent_text="\n".join(agent_lines),
    )
