"""Pillar 1 — A traveler can be invited.

Demo-script stage 1 (mvp.md §7): *"Advisor seeds a client + Voodoo Doll and sends
an invite. Traveler redeems the magic link."*

Acceptance (mvp.md Pillar 1):
  - Advisor creates client + Voodoo Doll in Command Center; invite is issued
    (single-use, lifecycle-tracked).
  - Traveler redeems magic link → role-aware redirect into /chat/[client_id].
  - Invite cannot be redeemed twice; unknown code / wrong email collapse to one
    indistinguishable response.

What's exercisable from the API/CLI seam today and what isn't:
  - ✅ Client + Dossier + invite issued atomically; lifecycle status readable.
  - ✅ The enumeration guarantee (unknown code and wrong email both → identical
    404) — a security invariant we assert directly.
  - ✅ The *post*-redemption landing: a linked traveler resolves their client and
    can open a chat session (the API-level shape of the /chat redirect).
  - ⛔ The *positive* redemption (real code → magic link) cannot run purely over
    HTTP: the invite code never crosses the HTTP boundary by design (auth.py),
    and the magic link is emailed. That assertion needs the F2 SMTP/DB harness;
    it is scaffolded here as a documented skip, not a false green.
"""

from __future__ import annotations

import flows  # local tests/e2e/flows.py (prepend import mode), mirrors tests/_helpers.py
import pytest

from ovb.agent import Conversation
from ovb.errors import ApiError
from ovb.scenario import Harness
from ovb.sdk import Ovb

pytestmark = pytest.mark.e2e


async def test_advisor_creates_client_and_invite_is_issued(advisor: Ovb) -> None:
    """Advisor creates a client; an invite is issued and lifecycle-tracked as pending."""
    # 1. Create client + Dossier + invite (atomic) — the Command Center "new client" action.
    client_id, _email = await flows.ensure_client(
        advisor,
        full_name="Pillar1 Subject",
        net_worth=250_000_000,
        party_notes="Couple + 1 child; private travel only.",
        children_ages=[9],
    )

    # 2. The client detail surface shows the invite in a single, derived lifecycle state.
    detail = await advisor.get_client(client_id)
    assert str(detail.invite_status) == "pending", detail.invite_status
    assert detail.invite_history, "an issued invite must appear in the history"
    assert str(detail.invite_history[0].status) in {"pending", "sent", "active"}

    # 3. It also shows up in the advisor's client list with the same status.
    listed = {str(c.id): c for c in await advisor.list_clients()}
    assert client_id in listed
    assert str(listed[client_id].invite_status) == "pending"


async def test_unknown_code_and_wrong_email_are_indistinguishable(harness: Harness) -> None:
    """The redeem endpoint must not let an attacker enumerate valid codes (D015)."""
    public = harness.public()

    # Two different *bad* inputs must collapse to the identical failure shape:
    # unknown code, and a (different) unknown code with an unrelated email.
    # (Domains use a real gTLD so EmailStr accepts them — see flows.unique_email.)
    with pytest.raises(ApiError) as first:
        await public.redeem_invite(code="not-a-real-code-aaaa", email="who@nomatch.dev")
    with pytest.raises(ApiError) as second:
        await public.redeem_invite(code="not-a-real-code-bbbb", email="other@nomatch.dev")

    assert first.value.status == second.value.status == 404
    # Same machine-readable detail → no signal leaks about which part was wrong.
    assert first.value.detail == second.value.detail == "invite_not_redeemable"


@pytest.mark.skip(
    reason="positive redemption needs the invite code, which never crosses the HTTP "
    "boundary (auth.py) + an emailed magic link — F2 SMTP/DB harness. Scaffold below."
)
async def test_traveler_redeems_invite_and_cannot_reuse_it() -> None:
    """Full positive + single-use path. Lights up with the F2 staging/SMTP harness.

    Intended flow (needs a side channel to read the issued code — DB or a test
    mailbox — because the API deliberately never returns it):

        1. advisor.create_client(...) → client_id, email.
        2. code = read_invite_code(client_id)          # DB/mailbox side channel (F2).
        3. await public.redeem_invite(code=code, email=email)   # 204; magic link sent.
        4. detail = await advisor.get_client(client_id)
           assert detail.invite_status == "consumed"
        5. with pytest.raises(ApiError) as exc:
               await public.redeem_invite(code=code, email=email)
           assert exc.value.status == 409                # single-use: already consumed.
    """
    ...


async def test_linked_traveler_lands_in_their_chat(
    traveler: Ovb, linked_traveler_client_id: str
) -> None:
    """Post-redemption landing (API shape of the role-aware /chat/[client_id] redirect).

    A redeemed traveler is a `client`-role JWT linked to a `clients` row. The
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
