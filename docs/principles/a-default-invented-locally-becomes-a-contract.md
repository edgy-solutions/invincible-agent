# A default invented locally gets reasoned about as a contract

**Named by invincible-agent-65, 2026-09-12**, from engine-cost's `limit: int = 8` — and the same
shape turns out to be underneath the routing defect that started the same investigation.

**Write a default into your own request model, and within a week you will find yourself reasoning
about it as though a caller chose it.** The number was local, arbitrary and yours. The authority
it acquires is not.

## The shape

    class EnumerateRequest(BaseModel):
        class_uri: str
        limit: int = 8          # <- invented here, by me

Then, at the site that uses it, written in good faith:

> *"the bound is the CALLER's declaration of what fits"*

**The caller omits it.** Every real request arrives without `limit`, so what applies is the
provider's own default — and the sentence describing it credits a decision nobody made. The
consequence was a card reading **"9 exist"** with an empty member list beside it: nine lots
against a bound of eight answered `too_many`, so the ask had nothing to render and degraded to
free text. **A refusal designed to protect an ask became the reason the ask was useless.**

**The tell is the word CALLER, or CONTRACT, or FLEET, in a sentence about a value your own file
sets.** Ask: *if I change this number, does anyone's request change?* If not, it is not a
contract term — it is your guess, wearing one.

## The reason it is hard to see: the local reasoning is CORRECT

Diverging from neighbouring providers really is a hazard — the fleet pays for
[`a-borrowed-name-is-a-claim`](a-borrowed-name-is-a-claim.md)-style disagreements constantly. So
"do not quietly disagree with engine-fin and engine-p about the default" is **good reasoning
reaching the wrong answer**, because the premise it rests on — that the number is shared — was
never checked. Three providers had each invented 8 separately. There was no fleet default to
agree with.

## The same shape, one layer up, in the same investigation

`_RESOLVE_FLOOR = 0.5`, invented independently by each instance provider. The bare-digit collision
scored **exactly 0.500** and cleared a `>=` gate — and because the pre-step treats a phone-book
hit as authoritative, a locally-invented threshold decided a routing question against a
classifier's 0.92. **A number chosen by one component silently became the fleet's definition of
"good enough to override".**

> Two defects, three days, one root: **a value invented in one file acquiring the standing of an
> agreement.**

## How to apply

- **Name the owner of every default in a comment**, and say whether it is stated anywhere else.
  *"8, chosen here, matching nothing"* ages honestly. *"the fleet default"* does not.
- **Prefer the value that CAN be derived.** A provider knows its own cardinality; a caller cannot.
  A default that the owning component is better placed to compute belongs there, computed.
- **Make the consumer state its requirement.** The durable fix here is that the disposition SENDS
  the limit it can render — after which the provider's default stops mattering at all. A default
  nobody relies on cannot be mistaken for an agreement.
- **Seal by READING the default, never by restating it.**

      default = EnumerateRequest(class_uri=LOT).limit
      # then assert every class enumerates at `default`

  A seal that restates the number is a second place for it to drift, and it will pass while the
  behaviour it describes is wrong. Reading it means raising or lowering the value moves the check
  with it, and a class growing past it fails in CI rather than on a card.
- **Assert over the whole population, not the instance that surfaced.** `ProductionLot` (9) was
  the one that broke; `RateTable` (12) was refusing identically and had simply never been asked.
  Fixing only what surfaced is [`a filed defect is a
  sample`](../plans/a-missing-mandatory-slot-is-a-400-not-an-ask.md)-shaped reasoning.

Related: [`reachability-is-a-property-of-a-path`](reachability-is-a-property-of-a-path.md) — both
are a claim that reads as checked because it is precise; [`a-green-check-proves-only-its-scope`](a-green-check-proves-only-its-scope.md).
