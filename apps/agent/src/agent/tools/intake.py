"""The intake hand-off tool — ends the immersive first conversation.

``complete_intake`` performs no backend write. Its whole purpose is the
``intake_complete`` SSE frame the translator derives from its result: the
immersive surface sees the frame, docks the chat into its normal column, and
lands the traveler on the trip dashboard — same session, conversation intact.
"""

from __future__ import annotations

from strands import tool


@tool
async def complete_intake() -> dict:
    """Signal that intake is done and the traveler should land in the trip.

    Call this when the traveler says they're ready to move on ("let's get
    started", "that's enough for now") or when the adventure's name, timing,
    and party are captured and the conversation is naturally landing. Record
    anything still unrecorded (title, brief, timing, party, facts) BEFORE
    calling this — after it fires, the immersive surface closes.

    After calling it, reply with a short parting line inviting the traveler
    to keep talking with you from the journal whenever they like.
    """
    return {"completed": True}
