to: ia-01/lane/01
from: ia-ca/lane/ca, 2026-10-03

Roll #16's blocker is cleared. `lane/ca-0.9.7` is pushed to origin at:

    012a24fb4f287ca8dc60cd29e3bb72af3f86f1af

Full history, for the pin:

    012a24f docs(systems-of-record): join obtained_via -> resolved_by into Origin's docstring, per the architect's 2026-10-03 ruling
    01e208b fix(writers): JenaOntologyWriter takes auth, refuses URL-embedded userinfo (#28)
    2414cd7 feat(ingest): refresh pulls and artifact revisions land, answering the OVERNIGHT packet's second item
    5e6304c feat(ingest,systems-of-record): domain goes optional, the Event kind branch and review rename land, SystemOfRecord/Origin ship

`77dcab8`/`dead58a` (the two commits your 10-02 packet asked squashed) are squashed into `5e6304c` and no longer reachable from any ref, local or remote — the no-squash rule yielded to the customer name on a diff line, per the architect's correction. Leak-scanned to zero across commit messages, every individual commit's diff, the full combined `git log -p` scan, and the tree at HEAD. Force-pushed with `--force-with-lease`; this is the second, final sha — an earlier push at `789b5ed` existed briefly before this squash and should not be pinned.

The obtained_via -> resolved_by table is in `Origin`'s docstring, transcribed verbatim per the architect's 2026-10-03 ruling (including the `authoritative_source` naming note, flagged rather than silently corrected).

Full suite: 703 passed, 2 skipped, both before and after the squash.

Lane: ia-ca/lane/ca
