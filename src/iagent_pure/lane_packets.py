"""Which lane a packet is for, and whether that lane has said it read it.

WHY THIS EXISTS, in the architect's own diagnosis: *"I told 32, 74 and the eo lane 'nothing
blocked on your side' this week while each had an unread packet sitting in their inbox — because
I rule to Lane 1, Lane 1 writes the packet, and nobody, including me, checks whether it was
READ."*

**The inbox fixed DELIVERY. It made "delivered" checkable and left "read" invisible** — so a lane
that ends its session on "idle until X rolls" never learns X rolled, and a session that is idle
does not know it has work. The cost was two days on the brief and the safety walk.

That is the census's own defect class: **a gap that exists and nothing prints.** So the remedy is
the shape every other one took this week — derive the population, partition it, print it as STATE
every run rather than as news.

    ia-32: 2 unread (5d, 3d), last commit 3d

would have been on the board on Thursday morning.

── READING IS AN ACT, NOT AN ASSUMPTION ────────────────────────────────────────────────────────

A packet is READ when the addressed lane commits a one-line stamp to it:

    read-by: ia-32/lane/32 2026-09-19

Delivery is the inbox; reading is the stamp; **both are on the rail**. "They were told" stops
being a claim anyone can make — including the architect, who named themselves in the diagnosis.

── ADDRESSING, DERIVED AND PARTITIONED ─────────────────────────────────────────────────────────

An explicit `to:` line wins. Failing that the H1 is read, because a convention already existed
before this module did — *"Packet for lane 91"*, *"Dispatch to the eo lane"* — and a derivation
that ignored the packets already written would start with an empty population.

**A packet matching neither is reported UNADDRESSED, never dropped.** An inbox that silently
discards what it cannot attribute is the same silence one layer down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: `to: invincible-agent/lane/91` — the explicit form, and the one a new packet should carry:
#: `<repo>/<branch>`, ruled 2026-10-07. A worktree name is not an address (`ia-74` is a directory;
#: `lane/74-acceptance-and-docs-subject` is the branch), and the repo segment is how a sender says
#: "another repo" (`cortex-ui/lane/cortex-60`). The legacy `to: ia-91/lane/91` is still READ and
#: still names the lane, but its name now comes from the BRANCH suffix like the ruled form's.
#:
#: A LANE TOKEN MAY CARRY A HYPHEN. `cortex-60` is a real session address and the first
#: character class here could not express it, so a packet addressed to that session could not
#: be addressed at all — the inbox seal reported it UNADDRESSED and the only way to quiet that
#: was to misname the recipient. A rule that cannot spell a real address is a rule that
#: manufactures its own violations.
#:
#: `to: invincible-agent/seat/architecture` — THE LANE-LESS SEAT, ruled 2026-09-26. Some seats own
#: no worktree: the architecture seat routes and never commits shared docs, so `ia-NN/lane/NN` has
#: nothing to name it with. Until this form existed those packets parsed as UNADDRESSED, which is
#: the `cortex-60` defect one door over — a real recipient the rule could not spell.
#:
#: THE ADDRESS IS THE SEAT, NOT THE REPO, by the same logic as the lane form: `ia-74/lane/74`
#: captures `74` and treats `ia-74` as where the work happens, so `<repo>/seat/<name>` captures
#: `<name>` and treats `<repo>` as where the inbox lives. Capturing the repo would file every seat's
#: packets under one address and make an inbox nobody could read.
#:
#: ── THREE THINGS THIS PATTERN GOT WRONG, all found by measuring the inbox rather than by reading
#: the regex ─────────────────────────────────────────────────────────────────────────────────────
#:
#: 1. `\s` CROSSES NEWLINES. `re.M` rebinds `^` and `$`; it does not stop `\s*` eating a line break,
#:    so `to: <repo>/seat/` with an empty name reached two lines down and addressed the packet to
#:    the word `body`. Every horizontal run here is `[ \t]` for that reason.
#:
#: 2. `$` REFUSED REAL ADDRESSES WITH A NOTE AFTER THEM. Two packets in this inbox are addressed to
#:    `lane/74` in the conventional form and were invisible to the census for a week, because the
#:    line carries a trailing clause — `to: ia-74/lane/74 — from ia-32/lane/32, 2026-09-21` and
#:    ``to: `ia-74` / `lane/74` (the consolidated worker)``. One of them is lane 32's closing
#:    handoff. The rule was refusing correctly-named recipients over punctuation, which is the
#:    `cortex-60` defect again, and the backtick form shows the same thing: people write the address
#:    the way the docs render it.
#:
#: 3. THE TRAILING CLAUSE IS ALLOWED ONLY AFTER A QUALIFIED ADDRESS — one carrying `/lane/` or
#:    `/seat/`. A BARE token must still own the whole line. This is not fussiness: four packets here
#:    say `to: the architect`, and a trailer permitted after a bare token would parse that as lane
#:    `the` — turning six honest UNADDRESSED reports into six confident deliveries to a lane that
#:    does not exist. A widened set with a stale description, where the new members are the junk.
#:
#: 4. A QUALIFIED ADDRESS NAMES A REPO BEFORE IT NAMES A LANE OR A SEAT, and the repo was never
#:    checked. `doc-tools/lane/7f` and `iagent-mesh-sdk/lane/ca` are real addresses in this inbox,
#:    for real recipients in OTHER repos, and the old pattern threw the repo away: `(?:ia-)?` is
#:    optional, so it matched zero characters and the whole hyphenated repo name — `doc-tools`,
#:    `iagent-mesh-sdk` — fell into the lane group whole. The census enumerates lanes from
#:    `origin/lane/*` in THIS repo, so an addressee named after a repo with no such branch here
#:    printed nowhere — not even UNADDRESSED, because the address had parsed fine. So `lrepo`
#:    and `srepo` below capture the WHOLE repo token, undecided, and `_addressed` is where
#:    internal vs. external gets decided — see `_is_internal_repo`.
def _is_internal_repo(token: str) -> bool:
    """True iff `token` names THIS repo — `invincible-agent` itself, or any `ia-<x>` worktree
    prefix (`ia-74`, `ia-eo`, `ia-cortex-60`, ...). Anything else — `doc-tools`,
    `iagent-mesh-sdk`, `cortex-ui` — is another repo's address, and for that address the repo
    IS the inbox: nobody in THIS tree can enumerate it, let alone mark it read, so it is reported
    as its own kind rather than mis-filed under a lane this repo does not have.

    DECIDED, NOT MEASURED: the qualified lane form used to let the leading `ia-` be optional, so
    a bare `74/lane/74` (no prefix at all) would have parsed as lane `74` by the old rule. No
    packet in this inbox is written that way — every in-repo address either carries `ia-` or
    is the bare token form (`_BARE`, which never reaches here) — so requiring the `ia-` prefix
    (or the literal repo name) costs nothing observed and is what keeps `doc-tools` from reading
    as internal.
    """
    t = token.lower()
    return t == "invincible-agent" or t.startswith("ia-")


_SEAT = (
    r"`?(?P<srepo>[A-Za-z0-9][A-Za-z0-9-]*)`?[ 	]*/[ 	]*`?seat/(?P<seat>[A-Za-z0-9][A-Za-z0-9-]*)`?"
)
_LANE = (
    r"`?(?P<lrepo>[A-Za-z0-9][A-Za-z0-9-]*)`?[ 	]*/[ 	]*`?(?P<lsuffix>lane/[A-Za-z0-9-]+)`?"
)
#: `to: OpenDDIL's agent` — THE ONE PROSE FORM, ruled alongside the "external" kind. OpenDDIL
#: has no repo and no branch in this tree at all; "their agent" is the only noun anyone here has
#: for the recipient, and nine packets already say it this way. It is QUALIFIED like the seat and
#: lane forms (may carry a trailing clause) because it is just as specific an address as they are
#: — the alternative was to leave it prose forever, which is the UNADDRESSED defect with a name
#: attached. NOT a general widening: only the exact `'s agent` suffix is accepted, so
#: `the architect` and `whoever takes the shared master tree` — genuinely unaddressable prose
#: — still fall through to UNADDRESSED, the control this module has carried since the
#: bare-token rule.
_PROSE_EXTERNAL = r"`?(?P<prose>[A-Za-z0-9][A-Za-z0-9-]*)`?'s[ 	]+agent"
_QUALIFIED = rf"(?:{_SEAT})|(?:{_LANE})|(?:{_PROSE_EXTERNAL})"
#: Only `— note`, `(note)`, `,` and `:` open a trailing clause. A bare space does not, so
#: `to: ia-74/lane/74 from ia-32` is still refused — stated here because the accepted set is a
#: claim, and the seal fires each of these rather than restating them.
_TRAILER = r"[ \t]*(?:[-—–(,:].*)?"
_BARE = r"(?:ia-)?(?P<bare>[A-Za-z0-9][A-Za-z0-9-]*)"

_TO = re.compile(
    rf"^[ \t]*to:[ \t]*(?:(?:{_QUALIFIED}){_TRAILER}|{_BARE}[ \t]*)$",
    re.M | re.I,
)

#: `read-by: ia-91/lane/91 2026-09-19` — the stamp. The date is recorded for the report and is
#: deliberately not parsed for correctness: a stamp with a wrong date is still a lane saying it
#: read the packet, and refusing it on format would make the honest act harder than skipping it.
#:
#: IT MUST SPELL EVERY FORM `_TO` SPELLS. Adding the seat form to the ADDRESS and not to the STAMP
#: would make a seat's packet PERMANENTLY UNREAD: the seat commits the one line the report asks
#: for, this regex does not match it, and the census goes on printing a standing gap against a seat
#: that did the work. That is the `cortex-60` defect with its sign flipped — not a recipient the
#: rule cannot name, but an ACT the rule cannot record — and it is worse than the original, because
#: the seat has no way to tell that its stamp did not count. So the two patterns carry the SAME
#: alternation, and a seal drives both from one address list rather than trusting them to match.
_READ_BY = re.compile(
    rf"^[ \t]*read-by:[ \t]*(?:{_QUALIFIED}|{_BARE})[ \t]*(?P<date>\S+)?",
    re.M | re.I,
)

#: `from: ia-74/lane/74, 2026-09-23` — the SENDER, read by the SAME grammar as `to:` and
#: `read-by:` rather than a second hand-written address regex: a sender address is exactly as
#: qualified or as bare as a recipient address, and a drift between two copies of "what counts as
#: an address" is how `_READ_BY` went stale before. Unlike `_TO`, a `from:` line in this inbox is
#: often NOT one of these forms at all — `invincible-agent/master (Lane 1)`, `lane/saf
#: (worktree ia-saf)` — and that is fine: `unanswered_over` treats an unparsed `from:` as
#: UNDECIDED, not as absent, because "I cannot tell who sent this" is a different fact from "this
#: was never addressed."
_FROM = re.compile(
    rf"^[ \t]*from:[ \t]*(?:(?:{_QUALIFIED}){_TRAILER}|{_BARE}[ \t]*)$",
    re.M | re.I,
)


def _addressed(m) -> tuple[str, str]:
    """The (name, kind) a matched address names. ONE reader for both patterns, so the address form
    and the stamp form cannot drift apart by being parsed in two places.

    `m.group(1)` was what both sites used before the seat form existed, and it is now a TRAP: the
    first named group in the alternation is `seat`, so a plain lane address makes `group(1)` None
    and every existing packet in the tree raises on `.lower()`. The named groups are the fix, and
    this helper is why there is only one place to get it wrong.
    """
    seat = m.group("seat")
    if seat:
        # A SEAT IS NEVER EXTERNAL, whatever repo prefix it carries. lane/74's ruled design
        # (2026-09-26, comment above, "THE ADDRESS IS THE SEAT, NOT THE REPO") captures `<name>`
        # and treats `<repo>` as only where the inbox lives, so `doc-tools/seat/architect` is the
        # architect seat's packet. External applies to the LANE form with a foreign prefix and to
        # `<Name>'s agent` only. The misses of a too-wide external rule land on the lane-less seat,
        # whose only evidence of existing is a packet addressed to it: it would leave the seat's
        # inbox and print under no seat row.
        return seat.lower(), "seat"

    lrepo = m.group("lrepo")
    if lrepo:
        if _is_internal_repo(lrepo):
            # THE LANE NAME IS ALWAYS THE BRANCH SUFFIX (ruled 2026-10-07: a worktree name is
            # not an address). `ia-74/lane/74-acceptance-and-docs-subject` is lane
            # `74-acceptance-and-docs-subject`, not `74`; `invincible-agent/lane/01` is `01`,
            # never `invincible-agent`, which no `origin/lane/*` branch matches.
            #
            # A LEGACY `ia-<x>` PREFIX IS INTERNAL, EVEN WHEN <x> LOOKS LIKE ANOTHER REPO'S
            # LANE (`ia-cortex-60/lane/cortex-60` stays lane `cortex-60` here). The scanner
            # must not guess: the ruled form is how a sender says "another repo", and the census
            # reports the legacy count (ADDRESS FORM) so the sender can re-address.
            name = m.group("lsuffix").split("/", 1)[1]
            return name.lower(), "lane"
        # EXTERNAL LANE (`doc-tools/lane/7f`, `iagent-mesh-sdk/lane/ca`). Unlike a seat, a lane is
        # owned by its repo -- `7f` here and `7f` in doc-tools are different branches -- so the repo
        # is kept: it is the only registry this address lives in.
        return f"{lrepo}/{m.group('lsuffix')}".lower(), "external"

    prose = m.group("prose")
    if prose:
        # `OpenDDIL's agent` — no repo to keep, because the address never had one.
        return prose.lower(), "external"

    # BARE token (`cortex-60`, `openddil`). Not qualified, so it cannot carry a trailing clause
    # — see `_TO` — and it is NEVER external: a bare word is pure lane-token syntax, with no repo
    # segment to test, and widening it would undo the very control `_TO`'s tests pin (`the` must
    # not become a lane).
    return m.group("bare").lower(), "lane"

def _form(m) -> str:
    """WHICH ADDRESS FORM matched: seat | repo (ruled `<repo>/lane/<b>`, internal or external) |
    worktree (legacy `ia-<w>/lane/<b>`) | prose | bare. Read from the same named groups as
    `_addressed`, so there is still one grammar and no second address regex."""
    if m.group("seat"):
        return "seat"
    lrepo = m.group("lrepo")
    if lrepo:
        return "worktree" if lrepo.lower().startswith("ia-") else "repo"
    return "prose" if m.group("prose") else "bare"


#: The conventions already in the tree, read from the H1.
_TITLE_FORMS = (
    re.compile(r"^#\s.*?\bfor\s+lane\s+([A-Za-z0-9]+)", re.I),
    re.compile(r"^#\s.*?\bto\s+the\s+([A-Za-z0-9]+)\s+lane\b", re.I),
    re.compile(r"^#\s.*?\bto\s+lane\s+([A-Za-z0-9]+)", re.I),
)


@dataclass
class Packet:
    path: str
    addressee: str | None          # lane id ("91") or seat name ("architecture"); None = unattributable
    read_by: list = field(default_factory=list)   # names that stamped it, of either kind
    source: str = "none"           # how the addressee was found: to | title | none
    #: WHICH REGISTRY the addressee is in — a lane (has a worktree and a branch), a lane-less
    #: seat, or (ruled alongside the "external" kind) a recipient in ANOTHER repo entirely, where
    #: the addressee string is the full qualified address (`doc-tools/lane/7f`) because the repo
    #: IS that recipient's only registry. This is a SECOND AXIS and not another value of `source`:
    #: `source` answers how the address was FOUND (explicit line, H1, nowhere) and `kind` answers
    #: what it NAMES. Folding them into one field is the mistake `route_status` and the
    #: disposition vocabulary were kept apart to avoid, and the cost is paid by the reader: the
    #: census enumerates lanes from `origin/lane/*`, which cannot enumerate a seat OR an external
    #: recipient, so it needs to ask this directly.
    kind: str = "lane"
    #: Who SENT this packet, by the same grammar `to:` and `read-by:` use (built via `_FROM`), and
    #: its kind. Both are None/"lane" (the dataclass default) when `from:` is absent or does not
    #: parse — which is NOT the same as "no sender": see `unanswered_over`, where an unparseable
    #: `from:` blocks the reply test entirely and the packet goes to UNDECIDED rather than being
    #: silently read as unanswered or as answered.
    sender: str | None = None
    sender_kind: str = "lane"
    #: Which address form the explicit `to:` used: repo | worktree | seat | prose | bare, or
    #: `title` (H1 fallback) / `none`. Reported by the census so legacy worktree addressing can be
    #: re-addressed; identity stays the bare name whatever the form.
    form: str = "none"

    @property
    def is_read(self) -> bool:
        """Read by the lane or seat it is ADDRESSED to. A stamp from another one is not a read.

        An unaddressed packet can never be read, which is why UNADDRESSED is reported as its own
        state rather than folded in with unread — they need different repairs.

        IDENTITY IS THE BARE NAME, ACROSS ALL KINDS (lane, seat, external). A lane called `x` and a seat called `x` would
        therefore read each other's packets. That is not defended here by qualifying the name —
        `read_by` is a list of bare names and a seal pins that shape — but by a seal asserting the
        two namespaces are DISJOINT, which fires when someone adds the colliding name, i.e. at the
        moment the ambiguity becomes real rather than at the moment it becomes possible.
        """
        return bool(self.addressee) and self.addressee in self.read_by


def parse_packet(path: Path) -> Packet:
    text = path.read_text(encoding="utf-8", errors="replace")
    head = "\n".join(text.splitlines()[:40])

    addressee, source, kind, form = None, "none", "lane", "none"
    m = _TO.search(head)
    if m:
        addressee, kind = _addressed(m)
        source, form = "to", _form(m)
    else:
        # THE TITLE FORMS NAME LANES ONLY, and deliberately stay that way: they exist to read
        # packets written before the inbox did, and no such packet addresses a seat.
        for tform in _TITLE_FORMS:
            t = tform.search(head)
            if t:
                addressee, source, form = t.group(1).lower(), "title", "title"
                break

    read_by = [_addressed(r)[0] for r in _READ_BY.finditer(text)]

    sender, sender_kind = None, "lane"
    fm = _FROM.search(head)
    if fm:
        sender, sender_kind = _addressed(fm)

    return Packet(path=path.as_posix(), addressee=addressee, read_by=read_by, source=source,
                  kind=kind, sender=sender, sender_kind=sender_kind, form=form)


def scan(sessions_dir: Path) -> list:
    """Every packet in the inbox, parsed. Sorted newest-first by filename, which carries the date."""
    if not sessions_dir.is_dir():
        return []
    return [parse_packet(p) for p in sorted(sessions_dir.glob("*.md"), reverse=True)]


def unread_by_lane(packets) -> dict:
    """lane -> [packets addressed to it and not stamped by it].

    LANES ONLY, since the seat form arrived. Its caller looks each key up against a branch derived
    from `origin/lane/*`, so a seat's packets landing in this dict would be counted and then
    printed by nobody — see `unread_by_seat`.
    """
    out: dict = {}
    for p in packets:
        if p.addressee and p.kind == "lane" and not p.is_read:
            out.setdefault(p.addressee, []).append(p)
    return out


def unread_by_seat(packets) -> dict:
    """seat -> [packets addressed to it and not stamped by it].

    WHY THIS IS A SEPARATE ENUMERATION AND NOT A FILTER ON THE SAME ONE. A lane's population comes
    from the branch list: the census can print `inbox clear` for a lane with no packets at all,
    because the lane exists whether or not anything is addressed to it. **A lane-less seat has no
    branch, so its only evidence of existing is a packet addressed to it** — the population has to
    be derived FROM THE PACKETS, and an unread count is all that can be reported.

    The consequence is worth stating where the code is, because it is the one blind spot this form
    keeps: a seat with an EMPTY inbox is indistinguishable from a seat that does not exist. That is
    the acceptable half of the trade (nothing is waiting on it either way), whereas the alternative
    — routing seat packets through `unread_by_lane` — loses the case that matters, a seat with work
    standing and no row anywhere to print it.
    """
    out: dict = {}
    for p in packets:
        if p.addressee and p.kind == "seat" and not p.is_read:
            out.setdefault(p.addressee, []).append(p)
    return out


def unaddressed(packets) -> list:
    """Packets naming neither a lane nor a seat. A NAMED state, not a silent drop — an inbox that
    discards what it cannot attribute is the same silence this module exists to end."""
    return [p for p in packets if not p.addressee]


def external_packets(packets) -> dict:
    """addressee -> [packets addressed to it], for every recipient in ANOTHER repo.

    SEPARATE FROM `unread_by_lane`/`unread_by_seat`, for the SAME reason `unread_by_seat` is
    separate from `unread_by_lane`: an external recipient has no branch here to enumerate from, so
    the population has to come FROM THE PACKETS. It differs from the seat case in one way that
    matters enough to drop the "unread" framing entirely: a seat's `read-by` stamp lands in THIS
    tree, where this module can see it, but an external recipient's stamp — if it ever wrote one —
    would land in ITS OWN tree, which this module can never read. Reporting "N unread" here would
    be a claim about silence on a channel we cannot listen to. All that can honestly be said is
    what was SENT and how old it is, so this returns every packet addressed externally, not only
    the unstamped ones — see the EXTERNAL block in `_lane_census.report_lanes`.
    """
    out: dict = {}
    for p in packets:
        if p.addressee and p.kind == "external":
            out.setdefault(p.addressee, []).append(p)
    return out


def _later(a, b) -> bool:
    """True if packet `b` is later than packet `a`: by filename date, then path order. A packet's
    filename is `YYYY-MM-DD-slug.md`, so a plain string compare on the filename already sorts by
    date first and then by the rest of the name (path order) — no second comparison is needed."""
    return Path(b.path).name > Path(a.path).name


def _replied(p, packets) -> bool:
    """True if some LATER packet in `packets` answers `p`: sent by whoever `p` was addressed to,
    and addressed back to whoever sent `p`. Both ends are read through `_addressed` — the same
    (name, kind) comparison `is_read` and the lane/seat enumerations use — so a reply is recognised
    in exactly the forms a `to:`/`from:` line can take, never by a second hand-matched rule.

    Requires `p.sender`: a packet whose own `from:` cannot be resolved has no sender to check a
    reply's `to:` against, so this is never called for one — see `unanswered_over`, which routes
    that case to UNDECIDED before reaching here.
    """
    for q in packets:
        if q is p or not _later(p, q):
            continue
        if (q.sender, q.sender_kind) == (p.addressee, p.kind) and \
                (q.addressee, q.kind) == (p.sender, p.sender_kind):
            return True
    return False


def unanswered_over(packets, *, now: float, age_of, hours: float = 48.0) -> tuple[dict, list]:
    """(addressee -> [packets addressed to it, unanswered, older than `hours`], [(packet, reason)
    UNDECIDED]), keyed by `(kind, addressee)` so a lane, a seat and an external recipient sharing a
    bare name never share a bucket.

    ANSWERED := stamped `read-by` by the addressee (`p.is_read`), OR a LATER packet that replies —
    see `_replied`. A packet whose OWN `from:` line does not parse can never be tested for the
    second half (there is nothing to check a reply's `to:` against), so it is neither answered nor
    unanswered: it goes to the UNDECIDED list with a reason, rather than being silently counted as
    either — a wrong "unanswered" sends someone chasing a reply that already happened off-grammar,
    and a wrong "answered" hides a packet nobody actually replied to.

    `age_of(path)` returns seconds-since-epoch for the packet's commit, or `None` if it is
    uncommitted. `None` is THE THIRD STATE and is excluded here rather than treated as "fresh" —
    an uncommitted packet has no age to compare against 48h, and reporting it as within the window
    would be exactly the silence the third state already is; see the worktree walk in
    `_lane_census.report_lanes` for where that state is actually surfaced. `now` and `age_of` are
    both injected so a test can fix time without a real clock or a real commit.
    """
    by_addressee: dict = {}
    undecided: list = []
    for p in packets:
        if not p.addressee or p.is_read:
            continue
        if not p.sender:
            undecided.append((p, "from: line did not parse -- cannot test for a reply"))
            continue
        if _replied(p, packets):
            continue
        age_s = age_of(p.path)
        if age_s is None:
            continue  # uncommitted: the third state, not fresh -- never counted here
        if (now - age_s) / 3600.0 > hours:
            by_addressee.setdefault((p.kind, p.addressee), []).append(p)
    return by_addressee, undecided
