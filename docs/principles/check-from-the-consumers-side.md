# The check-from-the-consumers-side law

> **Everything this project checks, it checks from the inside. The defects that survive are the
> ones that only appear from outside — and they land on a stranger.**

Not yet a fully-worked law; filed 2026-08-11 on **two instances in one week**, because the pattern
is the kind that produces a third quietly.

## The two instances

| defect | invisible from inside because | who it lands on |
|---|---|---|
| `iagent-mesh-sdk`'s unbound registration consumer | the platform registers via `register_engine_to_mesh` → `engine_mint`, which already binds the transport. **The unbound path was `MeshTool` — which this repo does not use to register.** Every in-repo test and every in-repo engine was fine. | an **externally-scaffolded engine** — the exact audience the package exists for — registering unminted and stopping under REQUIRE |
| `dag-tools[broker]`'s undeclared `redis` / `PyJWT` | both are module-level imports, and every environment that had ever run the gateway pulled them in transitively. Nothing in-repo installs the package the declared way. | whoever first runs `pip install "dag-tools[broker]"` — a gateway that **cannot import at all** |

**The common shape:** the repo's own usage pattern happens to avoid the broken path, so every
test, every deploy, and every reading from inside is green. The defect is not hidden by
complexity; it is hidden by **point of view**.

## Why this is worse than an ordinary blind spot

A hand-seeded cluster fails loudly for the next person who builds one — and that person is usually
you. A consumer-side defect fails for **someone who did not write it, in an environment you cannot
see, with your name on the package.** They cannot diagnose it (they do not know the working path
exists), and you cannot reproduce it (your environment is the one that works).

Both instances also share an aggravating factor: **the repo had just finished arguing it was
correct.** The SDK's commit invoked the one-implementation rule while leaving its own consumer
unbound; the gateway declared an installable extra that could not install. Confidence and exposure
were produced by the same commit.

## The check — and it has to be an ACT, not a review

Reading the code from inside cannot find these, because reading is the thing that has the wrong
point of view. The check is to *occupy the consumer's position*:

* **Install the package the declared way**, in a clean environment, and import what it ships.
  `pip install "<pkg>[<extra>]"` in a fresh venv, then `import` the deployed module.
* **Scaffold a consumer the way the docs tell a stranger to**, and run it — for the SDK, build a
  `MeshTool` engine from the template rather than testing the platform's own engines.
* **Ask of any shared component: which path does THIS repo not take?** That path is where the
  defect will be, precisely because nothing here exercises it.

## Status

**Two instances, no guard.** Per `[[naming-a-class-is-not-a-guard]]`, filing this changes nothing
by itself — a fresh-venv install check in CI would, and does not exist yet. Recorded so the third
instance is recognised as a third rather than met as a novelty.

Related: `[[consolidation-completes-at-the-last-consumer]]` (the SDK instance's own law) and
`[[bootstrap-state-debt]]`'s dependency dimension (the packaging instance's).
