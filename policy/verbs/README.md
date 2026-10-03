# `policy/verbs/` -- the SEED half of the declared stub verbs

A stub verb stands in for an spo_operation whose real verb is not served yet. Its row says what it
returns, rendered from the case context, and what retires it (`retired_by`). The step record says
STUB, so no reader takes the canned answer for a store read. `workflow_definition.load_stub_verbs`
reads this directory and every `policy/overlays/<name>/verbs/`.

**This directory is STRUCTURAL, and empty on purpose.** Every stub today is a programme's, so it
lives in an overlay. The directory exists, and is baked into the image, so a platform stub added
here later ships on arrival.

A verb declared twice, anywhere on the path, is refused.
