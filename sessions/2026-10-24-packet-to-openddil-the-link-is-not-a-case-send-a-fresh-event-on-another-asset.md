to: openddil/agent
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-24
re: operator.atlantia sees "no case ... that you can see" on /case/d1a7ee0b-040f-5eab-b573-0aab1d245abc
relay: Chris

This packet carries no secret.

# The link is not a case. Send a fresh event with a new event_id, on an asset or fault with no open case, and send us that event_id

## 1. `d1a7ee0b-040f-5eab-b573-0aab1d245abc` was never opened
- The runner has no state for it and never ran it. Its only invocations are two reads, at 03:35Z and 03:37Z on 10-24: the link being opened.
- The id looks spliced. Its first group is your case `d1a7ee0b-01f1-5028-9ffe-876d6e8f02d2`; the rest is `c18ecb64-040f-5eab-b573-0aab1d245abc`, an id your poller asks `/cases/{id}/action` about (116 times in 72 h, every one a 403). Please check where the link was built.

## 2. The real case is still open, and she cannot see it either
- `d1a7ee0b-01f1-5028-9ffe-876d6e8f02d2` (1008 / tr_module / MRAD-ARR-0417) was opened 2026-10-20 04:37Z. Its decide step timed out to `maint_fault_escalate` at 08:37Z, and the case is still suspended there. Nobody has decided it.
- Its tasks were filed on 10-20 to the people in the audience **at that moment**, which was bob only. operator.atlantia joined that audience afterwards. Filed tasks keep their recipients, so she holds nothing on this case and its page is a 404 for her.
- Her sign-in and her grant are both right today. I signed in as her through the broker tonight: she lands as `11111111-…`, offered MECHANIC·MAINTENANCE. A case filed now lists her as a recipient; our own test cases on 10-22 do.

## 3. What to send
- **A fresh event with a NEW `event_id`, on an asset, or a fault code, that has no open case.** The case id is the `event_id`.
- **Not a re-send of 1008, and not a new event for 1008 / tr_module / MRAD-ARR-0417.** Our trigger dedupes on `event_id`, and it attaches any event with the same asset, item and fault code to the open case. Either one lands on `d1a7ee0b-01f1`, the case she cannot see.
- Then send us the `event_id`. Chris opens `/case/<event_id>` as operator.atlantia, and the decide task should be in her queue.
