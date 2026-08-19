# Writing docs people actually read

**One rule: a tired reader on their phone should get the point in 10 seconds.**

Everything below serves that.

This applies to READMEs, `ai/` docs, epic and issue bodies, PR descriptions,
config file headers, and module docstrings. Code comments explaining *why* a
line exists are exempt — those are for the person reading that line.

---

## The 7 rules

### 1. Answer first. Then explain.

Lead with the conclusion in one bold sentence. The reasoning goes *after*, for
whoever wants it.

❌ "In order to understand the graded pool system, it is first necessary to
consider how the RSI gate selects suites…"

✅ **"`gold` = the tests we trust enough to gate on."**

### 2. One idea per line.

Break the paragraph. White space is not wasted space — it's how a scanning eye
finds the handle.

### 3. Short words. Concrete nouns.

| Don't | Do |
|---|---|
| utilize | use |
| in order to | to |
| facilitates the validation of | checks |
| it should be noted that | *(delete it)* |
| leverage the existing infrastructure | reuse what's there |

If a sentence survives deleting its first four words, delete them.

### 4. Say what breaks.

A feature description is half a doc. The other half is the failure it prevents.

❌ "The listener persists metric rows per test case."

✅ "The listener writes a metric row per test. **No rows = nothing on the
scoreboard.**"

### 5. Structure is navigation.

Headers, tables, bullets — so someone can jump straight to their bit.

Emoji as *anchors*, not decoration. One per item, and only when the list is
long enough that people need to find their place in it. A 3-item list doesn't
need them.

### 6. No hedging, no throat-clearing.

Cut: "it's worth noting", "arguably", "in some sense", "as previously
mentioned", "please be aware that".

If you're genuinely unsure, say **"unverified"** or **"guess:"** and move on.
That's information. Hedging is noise.

### 7. End with the gap.

What's still missing, still broken, still unknown. This is usually the most
useful part of the whole document — and the part that gets left out.

---

## The shape

Long or complex doc? Open with a **Plain version** block: 3–6 lines, no jargon,
that answers "what is this and why do I care."

Then the detail underneath, for whoever needs it.

The plain version is not a summary you write last. It's the thing you write
*first*, before you know if you understand the topic well enough to explain it.

---

## Before / after

**Before** — technically correct, unreadable:

> The `control:instrument` tag identifies test cases which assert that the
> verification instrumentation correctly surfaces a deliberately introduced
> defect, thereby validating the negative-detection capability of the harness
> measurement apparatus.

**After:**

> **`control:instrument` = we broke it on purpose, the test must catch it.**
>
> A suite that's all green tells you nothing if it *can't* go red.

Same facts. One is 34 words of fog, the other is 26 words you can act on.

---

## What this is not

- **Not dumbing down.** Precision goes up, not down — vague words are what make
  docs long. "It handles errors gracefully" is longer *and* says less than
  "on a timeout it retries once, then skips the model."
- **Not banning detail.** Put the detail below the plain version, where the
  people who need it will find it.
- **Not a licence to skip specifics.** File paths, exact commands, real numbers.
  "Run the tests" is useless; `make gold-check` is a doc.
- **Not for code comments.** A `# why this exists` note next to a tricky line
  follows the surrounding code's conventions, not this guide.

---

## The gap

Most of this repo predates this guide. `readme.md`, `ai/agents.md`, and the
older `ai/testing.md` sections are still written the old way.

Convert them **when you touch them**, not in one big sweep. A doc rewrite PR
that changes nothing else is hard to review and easy to get wrong.
