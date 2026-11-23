---
name: igf-finance-content
description: >-
  The niche layer for a trading, personal-finance and ecommerce education
  account: what to post, the hooks that work on money topics, the compliance
  line, and the post shapes that travel. Use before writing any reel, carousel
  or story for this account, when the user asks "what should I post about
  finance", "is this allowed", "how do I explain X", or when a draft sounds like
  every other finance page.
---

# igf-finance-content — the niche, not the container

`ig-reel`, `ig-caption` and `ig-carousel` know how to make a post. This skill
knows what a finance post should contain. Use both.

---

## The four post shapes that work on money content

Every good fintech post is one of these, and they are ordered by how well they
travel. Pick the shape before you pick the words.

### 1. The Reframe (the strongest)

Take something the audience believes and show the arithmetic that breaks it.

> **Belief:** "A 2% stop loss is safer than a 1% one."
> **Reframe:** "2% stops look safer. Four losses in a row is a 7.8% drawdown
> instead of 3.9%. The stop is not the risk; the number of times you can be
> wrong in a row is."

The post is the calculation, on screen, one line at a time. No conclusion until
the last beat. The reader should feel the shift, not be told about it.

### 2. The Rule, stress-tested

State the rule in the hook, then spend the body showing where it fails.

> "Never average down." Here is what averaging down does to your breakeven after
> a 20% fall, and the one case where it is arithmetic rather than hope.

This is the shape that earns saves. Saves are the strongest signal on the
platform for a finance account, because saving a post is someone planning to
use it.

### 3. The Loss, with the mechanism

A real loss, the number, and the rule that would have prevented it. No
motivation, no lesson-framing, no "this taught me so much".

> "I lost ₹42,000 on one position. The mistake was not the entry. It was that I
> sized before I had a stop, so the stop got moved to fit the size."

This is the shape that builds trust, because almost nobody posts it. It also
requires a real number from `brand/voice.md`'s proof section. If that section is
empty, this shape is unavailable: say so rather than inventing.

### 4. The Ecommerce Economics

Unit economics explained without a guru voice. CAC vs LTV, the cash-flow hole at
growth, why returns kill a D2C margin, what a 3x ROAS actually means after
shipping.

> "A 3x ROAS sounds fine until you subtract returns, shipping and the 18%
> gateway fee. Here is the same ad set at 3x and at 4.5x, and the number where
> it actually makes money."

Almost nobody does this well, which is why it travels.

---

## Hooks that work on money topics

`ig-reel` has 26 formulas. On this niche, five of them carry most of the weight,
and each has a specific failure mode:

| Formula | Works because | Ruins it |
| --- | --- | --- |
| **The Number** — "₹42,000, one position, one mistake." | Money is concrete. A number is checkable. | A number nobody can relate to, or one you made up. |
| **Nobody Tells You** — "Nobody tells you that your first ten trades are supposed to lose." | Names a gap in what they were taught. | Followed by something obvious. |
| **The Reframe** — "Your stop loss is not your risk." | Contradicts a belief they hold. | Not resolving it in the same 30 seconds. |
| **The Mistake** — "I moved my stop three times in one trade." | Specific, human, cheap to admit. | Turning it into a humble-brag about the recovery. |
| **The Cost** — "That 'free' demat account costs ₹1,400 a year." | Everyone has been told it is free. | Getting the arithmetic wrong in the comments. |

Run the hook through `hookscore.py` before you write the body. In this niche the
check that matters is **SPECIFICITY**, and the number to beat is 60: a finance
hook with no checkable number, name or rate in it is a hook that gets scrolled.

---

## The compliance line, as a writer rather than a lawyer

You are writing, not litigating. Four rewrites cover almost everything.

| Instead of | Write |
| --- | --- |
| "You should buy X" | "Here is what the position size would be if your stop is here" |
| "This made 40%" | "This is the arithmetic that produced 40%, and here is the one where it produced -18%" |
| "Guaranteed returns" | (delete the sentence; there is no honest version) |
| "SEBI registered" | Only with the registration number from `brand/credentials.json`. Otherwise delete. |
| "Never lose money" | "Here is how much you lose when you are wrong, and why that is survivable" |

The machine gate is `brand/compliance.json` and `python3 -m ig compliance`. Read
its rule IDs when it blocks you: it is telling you which belief slipped in.

**The test that catches almost everything:** would this line still be true, and
still useful, if the market went the other way tomorrow? If not, it is a
prediction, not a lesson. Cut it.

---

## Visual language for money content

Numbers are the visual. Not stock charts, not money raining, not a man in a suit.

- **One number per card, at 150-200px.** The number is the message.
- **The arithmetic on screen, line by line**, timed to the voiceover. Let the
  viewer do the sum a beat before you say it.
- **Green and red mean direction, never emotion.** Use the brand accent for the
  number that matters, and red only for a real loss. A page that is red and
  green everywhere reads as a trading signal feed, which is the opposite of what
  this account is.
- **No screenshots of a broker app.** They imply live positions, they date
  instantly, and they are the exact artefact that gets a finance account
  reported.

The repo's renderer (`python3 -m ig render spec.json`) does the number-first
cards, the timing and the captions. `brand/brand.json` holds the palette so
every card matches without you deciding anything.

---

## Story shapes that feed the DM funnel

A story's job on this account is not reach. It is to produce a message.

1. **The one-question poll** that splits the audience on a real belief ("Do you
   set the stop before or after you size?"). The minority gets an answer in the
   DMs, and the answers are next week's posts.
2. **The number, teased.** A card with a number and no explanation, then the
   explanation in the next frame. The people who reply "wait, what" are the
   people who will read the carousel.
3. **The keyword.** "Comment GUIDE and I will send the sizing sheet." One per
   week, maximum. More than that and the keyword stops meaning anything.

`ig-story` has the mechanics. The niche rule is: **every story ends with a
reason to reply, and every reply is a person you can talk to tomorrow.**

---

## What this account does not post

Write these down and refuse them, even when asked, because they are the four
ways a finance page loses its account or its credibility:

- Market predictions, "tomorrow's move", "levels to watch".
- P&L screenshots, win screenshots, "my students' results".
- Motivation with a chart behind it ("discipline is the bridge...").
- Anything with "financial freedom", "alpha", "passive income", "secret", or a
  countdown timer.

If the user asks for one of these, say what it costs them and offer the nearest
honest version. Usually that is the same post with the outcome removed and the
mechanism left in, and it is a better post.

---

## The checklist before any finance draft is finished

- [ ] The hook contains a number, a rate, or a named mistake.
- [ ] The body teaches a mechanism, not an outcome.
- [ ] No buy/sell instruction, no price level, no prediction.
- [ ] The disclosure is in, if any instrument is named.
- [ ] Every number is real, from `brand/voice.md` or the owner's answer.
- [ ] `python3 -m ig compliance` says PASS.
- [ ] `/ig-human` score is above 60, so it does not read as generated.
- [ ] The last line loops back to the first, so a second watch is free.
