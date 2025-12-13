from __future__ import annotations

import logging
import signal
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

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
        audio_interface = DefaultAudioInterface()
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
