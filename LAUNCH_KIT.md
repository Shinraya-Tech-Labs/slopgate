# 🚀 SlopGate Viral Launch Kit
### *The Playbook to Reach GitHub Repo of the Day & Trending #1*

---

## 1. Hacker News ("Show HN")

**Suggested Submission Time**: Tuesday or Wednesday at 8:00 AM EST (1:00 PM UTC / 6:30 PM IST) for peak algorithmic velocity.

**Title**:
> Show HN: SlopGate – Stop AI PR spam in open source using AST code invariants

**Body**:
```text
Hey HN,

Open source maintainers are drowning in AI-generated PR slop. As Daniel Stenberg (curl maintainer) recently put it, it has become an unintentional denial-of-service attack on open source projects.

Most "AI detector" tools try to detect "AI-sounding English prose" in PR descriptions. This is the wrong layer:
1. An LLM agent (Cursor, Claude Code, Antigravity) easily writes beautiful, fluent Markdown with bullet points.
2. It causes false positives on non-native English speakers who just used an LLM to polish their patch notes.

SlopGate does not judge your English. It enforces Code & Test Invariants via Python's AST in < 0.05 seconds:
- Test Tamper Guard: Catches deleted asserts, tautology swaps (`assert x is not None` instead of `== value`), and `except: pass` bypasses.
- Phantom Symbol Detector: Catches hallucinated packages and non-existent standard library calls (`json.loads_async`).
- Zero Dependencies: Runs entirely on standard library. No API keys, no LLM tokens billed.
- Runs as a 10-second GitHub Action or a local CLI (`pip install slopgate && slopgate demo`).

GitHub: https://github.com/Shinraya-Tech-Labs/slopgate
Release: https://github.com/Shinraya-Tech-Labs/slopgate/releases/tag/v0.1.0

I'd love your feedback on additional AST invariant rules you'd like to see.
```

---

## 2. Twitter / X Viral Launch Thread

**Tweet 1 (Hook)**:
> Open-source maintainers are currently burning out from a flood of AI-generated PR slop.
> 
> "AI detector" bots that check PR text don't work—agents write fluent English, and it punishes non-native speakers.
> 
> Today we’re launching SlopGate: an AST-based Code Integrity Shield. 🛡️
> 
> [Attach 20-second video of running `slopgate demo` catching a weakened assert]

**Tweet 2 (The Core Insight)**:
> Why does AI PR slop pass CI?
> 
> Because coding agents "fix" failing tests by:
> 1. Replacing `assert result == expected` with `assert result is not None`
> 2. Wrapping failing asserts in `try: ... except: pass`
> 3. Inventing fake APIs like `json.loads_async()`
> 
> SlopGate catches all 3 in < 50ms using Python AST.

**Tweet 3 (Zero Dependencies)**:
> No API keys. No LLM tokens billed. Zero external dependencies.
> 
> You can drop it into your repository with one command:
> `slopgate install`
> 
> Or add the composite GitHub Action:
> `uses: Shinraya-Tech-Labs/slopgate@main`

**Tweet 4 (Call to Action)**:
> Star the repo and add the shield badge to your README:
> ⭐️ https://github.com/Shinraya-Tech-Labs/slopgate
> 
> Let's protect open-source maintainers.

---

## 3. Reddit Launch Post (`r/programming` & `r/opensource`)

**Title**:
> We built SlopGate: An open-source AST code shield to stop AI PR spam and test tampering

**Body**:
```text
Over 60% of open-source maintainer capacity is now swallowed by maintenance and triage. 

A growing portion of that is AI PR slop: pull requests that look superficially competent, but pass CI by weakening test assertions or adding phantom dependencies.

We built SlopGate as a zero-dependency, open-source GitHub Action and CLI that evaluates code invariants rather than guessing whether the English description was written by ChatGPT:

1. Test Tamper Protection: Intercepts deleted assertions and tautologies (`assert x is not None`).
2. Phantom Symbol Guard: Flags uninstalled packages and hallucinated stdlib methods.
3. Repro Verification: Checks if a bugfix includes a test case.

It runs locally with `pip install slopgate` and `slopgate demo`, or as a drop-in GitHub Action.

Full repo & documentation: https://github.com/Shinraya-Tech-Labs/slopgate

Feedback and PR contributions (which SlopGate will audit!) are welcome.
```

---

## 4. Upstream Show & Tell Outreach

Open polite, value-adding issues or discussion threads in maintainer communities discussing AI PR policies:
- Mention how AST invariant checking completely avoids the false-positive drama of text-based AI detectors.
- Link directly to the live demo: `https://github.com/Shinraya-Tech-Labs/slopgate`
