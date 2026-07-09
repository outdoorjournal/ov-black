"""Human messaging channel — threads + messages, with NO agent turn (M006/PS7).

This is the "Advisor" people-circle in the planner shell's concierge: a durable
conversation between the traveler, their advisor, and (once they have logins)
that trip's party. Per Q13 = UNIFY it writes the same ``threads`` / ``messages``
/ ``thread_participants`` store the AI channel will share in PS8 — but PS7 sends
only human messages (``author_kind`` ∈ {traveler, advisor}); Artemis is summoned,
not standing, so it never posts here until the PS8 bridge.

Authorization is enforced HERE (the API connects as the owner role, bypassing
RLS; the 0037 policies are defense-in-depth). Access mirrors the agent service:
an advisor who owns the client, or the client themself. Every failure collapses
to a single not-found outcome at the router so a caller cannot probe which
threads or clients exist (D015).

Redaction discipline: message ``content`` MUST NEVER appear in a log record —
only ids, kinds, counts. A human thread's audience is ``traveler``, so the PS8
disclosure invariant (Dossier/OSINT/net-worth never in a client-visible thread)
already applies to everything written here.
"""

from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Client,
    Itinerary,
    Message,
    SessionAudience,
    Thread,
    ThreadActorKind,
    ThreadKind,
    ThreadParticipant,
)
from app.services.agent import ActorContext, _jit_backfill_client_auth_user_id

logger = logging.getLogger("ov_black.messaging.service")


class MessagingOutcome(str, enum.Enum):
    """Terminal states of the messaging service operations."""

    OK = "ok"
    CLIENT_NOT_FOUND = "client_not_found"
    FORBIDDEN = "forbidden"
    THREAD_NOT_FOUND = "thread_not_found"


@dataclass(frozen=True, slots=True)
class ThreadContext:
    """A resolved thread plus its owning client (for authz + participant seed)."""

    thread: Thread
    client: Client


# ── author-kind mapping ─────────────────────────────────────────────────────


def _author_kind_for(actor: ActorContext) -> ThreadActorKind:
    """Map a request principal to the human author kind. Only humans post here."""
    if actor.actor_kind == "advisor":
        return ThreadActorKind.advisor
    return ThreadActorKind.traveler


# ── access ──────────────────────────────────────────────────────────────────


async def _enforce_client_access(
    session: AsyncSession,
    *,
    actor: ActorContext,
    client: Client,
    backfill: bool = False,
) -> MessagingOutcome:
    """OK / FORBIDDEN for (actor, client), mirroring the agent service.

    - advisor: must own the client (``clients.owner_id``).
    - user: must be the signed-in client (``clients.auth_user_id``). When
      ``backfill`` is set and the link is not yet established, we JIT-populate it
      on first human-channel access — same as the agent service's POST /sessions.
    """
    if actor.actor_kind == "advisor":
        if actor.user_id is None or client.owner_id != actor.user_id:
            return MessagingOutcome.FORBIDDEN
        return MessagingOutcome.OK
    if actor.actor_kind == "user":
        if actor.user_id is None:
            return MessagingOutcome.FORBIDDEN
        if client.auth_user_id is None and backfill:
            await _jit_backfill_client_auth_user_id(session, client=client, user_id=actor.user_id)
        if client.auth_user_id != actor.user_id:
            return MessagingOutcome.FORBIDDEN
        return MessagingOutcome.OK
    # actor_kind == 'agent' does not post in the human channel (PS8 summons it).
    return MessagingOutcome.FORBIDDEN


# ── participants ─────────────────────────────────────────────────────────────


async def _ensure_participant(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_kind: ThreadActorKind,
) -> None:
    """Idempotently add one human participant to a thread.

    Uses a savepoint so a UNIQUE-violation race (two accesses seeding the same
    member) is swallowed without poisoning the outer transaction.
    """
    exists = (
        await session.execute(
            select(ThreadParticipant.actor_id).where(
                ThreadParticipant.thread_id == thread_id,
                ThreadParticipant.actor_id == actor_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return
    try:
        async with session.begin_nested():
            session.add(
                ThreadParticipant(thread_id=thread_id, actor_id=actor_id, actor_kind=actor_kind)
            )
    except IntegrityError:
        pass  # a concurrent access seeded the same participant — fine.


async def _seed_human_participants(
    session: AsyncSession, *, thread: Thread, client: Client
) -> None:
    """Seed the standing human members of a client's human thread.

    Today that is the client's own auth user (traveler) + the advisor owner.
    Party members join once they have logins — the model already carries them
    via ``thread_participants``; there is just no login to attach yet.
    """
    if client.auth_user_id is not None:
        await _ensure_participant(
            session,
            thread_id=thread.id,
            actor_id=client.auth_user_id,
            actor_kind=ThreadActorKind.traveler,
        )
    await _ensure_participant(
        session,
        thread_id=thread.id,
        actor_id=client.owner_id,
        actor_kind=ThreadActorKind.advisor,
    )


# ── open-or-create ───────────────────────────────────────────────────────────


async def open_or_create_human_thread(
    session: AsyncSession,
    *,
    actor: ActorContext,
    client_id: uuid.UUID,
    itinerary_id: uuid.UUID | None = None,
) -> tuple[MessagingOutcome, Thread | None]:
    """Get — or create — the single human thread for a scope.

    Scope = ``(client_id, itinerary_id, audience='traveler')``. ``itinerary_id``
    NULL = basecamp scope (you ↔ advisor); non-null = that trip's thread
    (you ↔ advisor ↔ party). The two partial unique indexes in 0037 guarantee at
    most one live human thread per scope, so this is a stable get-or-create.
    """
    client = (
        await session.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        return MessagingOutcome.CLIENT_NOT_FOUND, None

    access = await _enforce_client_access(session, actor=actor, client=client, backfill=True)
    if access is not MessagingOutcome.OK:
        return access, None

    if itinerary_id is not None:
        owner_cid = (
            await session.execute(select(Itinerary.client_id).where(Itinerary.id == itinerary_id))
        ).scalar_one_or_none()
        if owner_cid is None or owner_cid != client_id:
            # Hide a foreign itinerary behind the standard FORBIDDEN → 404.
            return MessagingOutcome.FORBIDDEN, None

    thread = await _get_or_create_scope_thread(
        session, client_id=client_id, itinerary_id=itinerary_id
    )

    await _seed_human_participants(session, thread=thread, client=client)
    await session.commit()
    return MessagingOutcome.OK, thread


async def _get_or_create_scope_thread(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    itinerary_id: uuid.UUID | None,
) -> Thread:
    """The stable get-or-create for a scope's single live human thread.

    Extracted from :func:`open_or_create_human_thread` so the agent's
    escalation write (:func:`post_agent_thread_message`) reuses the same
    unique-index-backed resolution without the human-caller access gate —
    the agent token is already scoped to the client.
    """
    scope_match = (
        Thread.itinerary_id.is_(None)
        if itinerary_id is None
        else Thread.itinerary_id == itinerary_id
    )
    thread = (
        await session.execute(
            select(Thread).where(
                Thread.client_id == client_id,
                Thread.kind == ThreadKind.human,
                Thread.audience == SessionAudience.traveler,
                scope_match,
                Thread.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if thread is None:
        thread = Thread(
            client_id=client_id,
            itinerary_id=itinerary_id,
            kind=ThreadKind.human,
            audience=SessionAudience.traveler,
        )
        session.add(thread)
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent open won the unique index — reuse the winner.
            await session.rollback()
            thread = (
                await session.execute(
                    select(Thread).where(
                        Thread.client_id == client_id,
                        Thread.kind == ThreadKind.human,
                        Thread.audience == SessionAudience.traveler,
                        scope_match,
                        Thread.archived_at.is_(None),
                    )
                )
            ).scalar_one()
        else:
            await session.refresh(thread)
            logger.info(
                "messaging.thread.open",
                extra={
                    "thread_id": str(thread.id),
                    "client_id": str(client_id),
                    "itinerary_scoped": itinerary_id is not None,
                },
            )
    return thread


# ── load + authz for an existing thread ─────────────────────────────────────


async def _load_thread(
    session: AsyncSession,
    *,
    actor: ActorContext,
    thread_id: uuid.UUID,
) -> tuple[MessagingOutcome, ThreadContext | None]:
    row = (
        await session.execute(
            select(Thread, Client)
            .join(Client, Client.id == Thread.client_id)
            .where(Thread.id == thread_id)
        )
    ).first()
    if row is None:
        return MessagingOutcome.THREAD_NOT_FOUND, None
    thread, client = row
    access = await _enforce_client_access(session, actor=actor, client=client)
    if access is not MessagingOutcome.OK:
        return access, None
    return MessagingOutcome.OK, ThreadContext(thread=thread, client=client)


async def _mark_thread_read(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    actor: ActorContext,
) -> None:
    """Stamp the reading actor's ``last_read_at = now()`` (ADV-14 unread signal).

    A thread counts as *unread* for a participant while messages authored by
    *others* are newer than their ``last_read_at`` — the advisor awareness feed
    reads exactly that to know a client is waiting on a reply. Marking on list
    keeps the clear-on-read zero-UI: opening the thread in the ``HumanThread``
    panel (which lists messages) is what silences the badge. Best-effort — the
    reader may not be seeded yet (e.g. an itinerary thread the counterpart
    opened), so we ensure the row first, then stamp.
    """
    assert actor.user_id is not None
    await _ensure_participant(
        session,
        thread_id=thread_id,
        actor_id=actor.user_id,
        actor_kind=_author_kind_for(actor),
    )
    await session.execute(
        update(ThreadParticipant)
        .where(
            ThreadParticipant.thread_id == thread_id,
            ThreadParticipant.actor_id == actor.user_id,
        )
        .values(last_read_at=func.now())
    )
    await session.commit()


async def list_messages(
    session: AsyncSession,
    *,
    actor: ActorContext,
    thread_id: uuid.UUID,
) -> tuple[MessagingOutcome, list[Message]]:
    """Every non-removed message in a thread, oldest first.

    Listing a thread marks it read for the caller (``last_read_at``) so the
    ADV-14 awareness feed's unread count self-clears when the advisor opens it.
    """
    outcome, ctx = await _load_thread(session, actor=actor, thread_id=thread_id)
    if ctx is None:
        return outcome, []
    rows = (
        (
            await session.execute(
                select(Message)
                .where(
                    Message.thread_id == thread_id,
                    Message.removed_at.is_(None),
                )
                .order_by(Message.created_at, Message.id)
            )
        )
        .scalars()
        .all()
    )
    if actor.user_id is not None:
        await _mark_thread_read(session, thread_id=thread_id, actor=actor)
    return MessagingOutcome.OK, list(rows)


async def send_message(
    session: AsyncSession,
    *,
    actor: ActorContext,
    thread_id: uuid.UUID,
    content: str,
    parent_message_id: uuid.UUID | None = None,
) -> tuple[MessagingOutcome, Message | None]:
    """Post one HUMAN message — no agent turn (that is PS8's @-mention bridge)."""
    outcome, ctx = await _load_thread(session, actor=actor, thread_id=thread_id)
    if ctx is None:
        return outcome, None

    # The sender becomes a participant if they weren't already (advisor/traveler
    # both reach here through the access gate above).
    if actor.user_id is not None:
        await _ensure_participant(
            session,
            thread_id=thread_id,
            actor_id=actor.user_id,
            actor_kind=_author_kind_for(actor),
        )

    message = Message(
        thread_id=thread_id,
        author_kind=_author_kind_for(actor),
        author_id=actor.user_id,
        content=content,
        parent_message_id=parent_message_id,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    logger.info(
        "messaging.message.sent",
        extra={
            "thread_id": str(thread_id),
            "message_id": str(message.id),
            "author_kind": message.author_kind.value,
        },
    )
    return MessagingOutcome.OK, message


async def post_agent_thread_message(
    session: AsyncSession,
    *,
    client_id: uuid.UUID,
    itinerary_id: uuid.UUID | None,
    content: str,
) -> tuple[MessagingOutcome, Message | None]:
    """The agent's escalation write (AGT-4): one ``author_kind='artemis'`` message
    onto the scope's human thread, creating the thread if it doesn't exist yet.

    Unlike :func:`send_message` this takes no human principal — the caller is the
    agent-internal route, whose per-session token is already bound to
    ``client_id`` (the same trust model as the fact writes). The itinerary
    ownership check still runs so a mis-pinned session cannot post into another
    client's trip thread. Mirrors ``summon_artemis_in_thread``'s message shape
    (``author_id`` NULL, attribution via ``author_kind``).
    """
    client = (
        await session.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        return MessagingOutcome.CLIENT_NOT_FOUND, None

    if itinerary_id is not None:
        owner_cid = (
            await session.execute(select(Itinerary.client_id).where(Itinerary.id == itinerary_id))
        ).scalar_one_or_none()
        if owner_cid is None or owner_cid != client_id:
            return MessagingOutcome.FORBIDDEN, None

    thread = await _get_or_create_scope_thread(
        session, client_id=client_id, itinerary_id=itinerary_id
    )
    await _seed_human_participants(session, thread=thread, client=client)

    message = Message(
        thread_id=thread.id,
        author_kind=ThreadActorKind.artemis,
        author_id=None,
        content=content,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    logger.info(
        "messaging.message.sent",
        extra={
            "thread_id": str(thread.id),
            "message_id": str(message.id),
            "author_kind": message.author_kind.value,
        },
    )
    return MessagingOutcome.OK, message
