"""Pillar 1 — A traveler can be added and signs in by email.

Demo-script stage 1 (mvp.md §7): *"Advisor seeds a client + Dossier; the client
gets a welcome email and signs in with an email magic link."*

There is no invite code anymore — adding a client provisions their Supabase auth
row and emails a code-free welcome sign-in link. After that, sign-in is the plain
``POST /auth/login`` magic-link flow. The advisor can see whether the client has
signed in yet (``access_status`` pending → active, plus ``accepted_at``) and can
"nudge" a pending client by re-sending the welcome link.

What's exercisable from the API/CLI seam today and what isn't:
  - ✅ Client + Dossier created atomically; a welcome email is sent; status is
    readable as "pending" with no accepted_at until first sign-in.
  - ✅ Resending the welcome link to a pending client (the advisor nudge).
  - ✅ The /auth/login enumeration guarantee — an unknown email collapses to the
    same 204 as a real one, so it can't be used to probe who has an account.
  - ✅ The *post*-login landing: a linked traveler resolves their client and can
    open a chat session (the API-level shape of the /chat redirect).
  - ⛔ The *positive* sign-in (clicking the emailed magic link) cannot run purely
    over HTTP — the link is emailed and never returned by the API. That needs the
    F2 SMTP/mailbox harness; it is scaffolded here as a documented skip.
"""

from __future__ import annotations

import flows  # local tests/e2e/flows.py (prepend import mode), mirrors tests/_helpers.py
import pytest

from ovb.agent import Conversation
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


async def test_advisor_adds_client_and_welcome_is_sent(advisor: Ovb) -> None:
    """Advisor adds a client; status is pending (welcome sent, not yet signed in)."""
    # 1. Create client + Dossier (atomic) — the Command Center "new client" action.
    #    A code-free welcome sign-in link is emailed as part of this call.
    client_id, _email = await flows.ensure_client(
        advisor,
        full_name="Pillar1 Subject",
        net_worth=250_000_000,
        party_notes="Couple + 1 child; private travel only.",
        children_ages=[9],
    )

    # 2. The detail surface shows the client hasn't signed in yet.
    detail = await advisor.get_client(client_id)
    assert str(detail.access_status) == "pending", detail.access_status
    assert detail.accepted_at is None, "a brand-new client has not signed in yet"

    # 3. It shows up in the advisor's client list with the same status.
    listed = {str(c.id): c for c in (await advisor.list_clients()).clients}
    assert client_id in listed
    assert str(listed[client_id].access_status) == "pending"


async def test_advisor_can_resend_welcome_to_pending_client(advisor: Ovb) -> None:
    """The advisor "nudge": re-send the welcome link while the client is pending."""
    client_id, _email = await flows.ensure_client(advisor, full_name="Pillar1 Nudge")
    # Resend is a no-op-safe 204 while the client hasn't signed in. (Once they
    # have, the API refuses with 409 client_already_accepted — not exercisable
    # here without the sign-in side channel.)
    await advisor.resend_welcome(client_id)


async def test_login_unknown_email_does_not_enumerate(harness: Harness) -> None:
    """POST /auth/login collapses unknown email into the same 204 (D015)."""
    public = harness.public()
    # No raise: an unknown email is treated exactly like a real one so the
    # endpoint can't be used to probe which emails have accounts.
    await public.login(email="who@nomatch.dev")


@pytest.mark.skip(
    reason="positive sign-in needs the emailed magic link, which never crosses the "
    "HTTP boundary — F2 SMTP/mailbox harness. Scaffold below."
)
async def test_traveler_signs_in_via_magic_link() -> None:
    """Full positive sign-in path. Lights up with the F2 staging/SMTP harness.

    Intended flow (needs a test mailbox to read the emailed link):

        1. advisor.create_client(...) → client_id, email.
        2. link = read_welcome_link(email)          # mailbox side channel (F2).
        3. follow `link` → session established; clients.auth_user_id backfilled.
        4. detail = await advisor.get_client(client_id)
           assert detail.access_status == "active"
           assert detail.accepted_at is not None
    """
    ...


async def test_linked_traveler_lands_in_their_chat(
    traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """Post-sign-in landing (API shape of the role-aware /chat/[client_id] redirect).

    A signed-in traveler is a `client`-role JWT linked to a `clients` row. The
    web redirect lands them in their chat; the API-level invariant is that the
    traveler resolves *their own* client and can open a session for it.
    """
    # 1. The traveler resolves exactly one client — their own (the redirect target).
    resolved = str((await traveler.my_client()).client_id)
    assert resolved == linked_traveler_client_id

    # 2. They can open a chat session for that client (the landing page's first call).
    convo = await Conversation.open(traveler, client_id=linked_traveler_client_id)
    assert convo.session_id
    assert convo.client_id == linked_traveler_client_id
