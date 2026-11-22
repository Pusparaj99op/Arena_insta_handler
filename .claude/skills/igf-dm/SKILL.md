---
name: igf-dm
description: >-
  Handle the account's Instagram inbox: read new comments and DMs, decide what
  deserves a reply, deliver keyword files, escalate the questions that could cost
  someone money, and keep the conversation inside Meta's rules. Use when the user
  says "check my DMs", "reply to comments", "someone asked about pricing", "how
  do I answer this", "the inbox is a mess", or when the webhook reports new
  events.
---

# igf-dm — the inbox, without getting the account restricted

The inbox is where this account makes money and where it can get banned. Both
come down to one question: **did the person move first?**

The code in `automation/ig/social.py` answers that question and will refuse to
send when the answer is no. Read what it refused before you write anything:
`state/needs_human.jsonl` is the queue of things a human must decide.

---

## The four rules the code enforces (know them)

1. **They start, you reply.** A conversation begins with their DM, their story
   reply, their story mention, or their comment. Cold DMs are not a growth
   tactic; they are a restriction with extra steps.
2. **24 hours of free-form.** After their last message you have 24 hours to say
   anything. After that only the `HUMAN_AGENT` tag (7 days, app review, a human
   typing) is allowed. The code checks this on every send.
3. **One private reply per comment, ever, within 7 days.** The comment-keyword
   automation lives and dies on this. You do not get a second DM for the same
   comment, and deleting the comment does not reset it.
4. **Say it is automated, and offer a human.** The first automated message says
   so, and the word HUMAN hands the thread over for good. `human_takeover` is
   sticky in `state/dm_conversations.json`.

---

## The triage, in the order that matters

Run `python3 -m ig queue --status drafted` first. Then sort what is left:

| What it is | What it gets | Why |
| --- | --- | --- |
| **Keyword comment** (`GUIDE`, `SHEET`) | One private reply with the file. Nothing else. | They asked for one thing. Delivering more is how you get muted. |
| **A real question** | A short answer, then one question back. | The back-and-forth is the follow. |
| **Price / mentorship** | The offer in one line, then "reply DETAILS". | A link in the first message gets flagged; a word they type does not. |
| **Tax, legal, portfolio, "should I sell X", complaint** | Acknowledge, name the human, give one general principle, stop. | This is the set that gets screenshotted. Never answer these yourself. |
| **Collab pitch** | Ask for the one-paragraph version: what, what it pays, when. | Filters 90% of them honestly. |
| **Praise** | One line, specific to what they said. | Generic thanks reads as a bot. |
| **Troll** | Nothing. | Replying feeds it; the block button exists. |
| **Spam / follow-for-follow** | Nothing, and do not engage. | |

---

## What a good reply looks like here

```
{Name}, {the answer in one sentence}.

{The one thing that makes it useful: the number, the rule, or the risk they
did not mention.}

{One question they can answer in four words.}
```

Three short paragraphs. No links unless they asked. No "hope this helps". No
emoji unless `brand/voice.md` says so.

**Before it goes out, run it:**

```bash
cd automation
python3 -m ig check-dm "the message text"      # what the agent would do
python3 -m ig compliance "the reply text"      # the fintech gate
```

If the compliance verdict is `BLOCK`, do not soften it: rewrite it. The rule IDs
in the report tell you which line did it.

---

## The keyword funnel, which is most of the inbox

Someone comments `GUIDE`. Three things should happen, in this order:

1. **A public reply on their comment** ("sent, check your DMs") so the next
   person scrolling sees that commenting works.
2. **One private reply** with the file and one line on how to use it.
3. **Nothing else.** No follow-up sequence. A follow-up requires them to reply
   first, and if they reply, that is a new conversation with a new 24-hour clock.

The delivery lines live in `brand/keywords.json` under `how_to`, because only
the owner knows whether the file is a PDF, a link or a ManyChat flow. Never
invent a delivery instruction.

**Pick the keyword for the next post before writing the post.** The best one is
a noun the audience wants and nobody has: `CHECKLIST` beats `INFO`, `SHEET`
beats `DOWNLOAD`. One syllable is better than two.

---

## Escalation, in the owner's voice

When the agent escalates, you write the reply as the owner. The shape that works:

```
{Name}, this one needs a person rather than a template, so {their name / the
desk} will come back to you {when}.

In the meantime, the general principle is: {one true sentence that is not advice}.
```

Then actually do the human part: `state/needs_human.jsonl` has everything, with
`conversation_id` or `comment_id` to reply to. If the owner does not answer
within the 24-hour window, the only legitimate way to follow up later is the
`HUMAN_AGENT` tag, and only if it is approved for the app.

---

## Metrics that matter in the inbox

- **Reply rate** to the keyword comment. If under 60%, the file is wrong, not
  the automation.
- **Escalation rate.** If more than 1 in 5 DMs needs a human, the content is
  inviting the wrong questions: stop asking for them.
- **Time to first reply.** Under 15 minutes converts; over an hour does not.
- **Threads abandoned** (their message, no reply ever). This number is the
  account's real reputation, not its follower count.

Log these weekly in `state/metrics.jsonl` with `python3 -m ig tick` output so
the monthly audit has something to read.

---

## What this skill will not do

It will not cold DM, it will not message a follower who has not spoken, it will
not run a mass follow/unfollow, and it will not answer a regulated question in
the owner's name. Those are not limitations to work around; each one is a way
real accounts get permanently disabled, and this one is a business.
