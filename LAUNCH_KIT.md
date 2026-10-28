# 🚀 SlopGate Perfected Launch Kit
### *Engineered from Real-Time HN & r/Python Viral Analysis*

---

## 1. Hacker News ("Show HN") — The 390+ Upvote Blueprint

> **HN Submission Rules to Prevent Auto-Removal**:
> 1. **Submission Type**: Click **Submit**, enter the URL directly: `https://github.com/Shinraya-Tech-Labs/slopgate`.
> 2. **Title**: Keep it lowercase/sentence case, no adjectives like "super", "best", "blazing".
> 3. **The First Comment Rule**: Immediately (within 60 seconds of submitting), open your post and add the founder comment below. HN rewards honesty about design trade-offs and zero-fluff technical mechanics.

### Title to Submit:
```text
Show HN: SlopGate – AST-based code integrity check for pull requests
```

### URL to Submit:
```text
https://github.com/Shinraya-Tech-Labs/slopgate
```

### Your Immediate First Comment (Copy & Paste):
```text
Hey HN,

I kept seeing open-source maintainers express the exact same exhaustion: dealing with AI-generated pull requests that look plausible on the surface, but pass CI by weakening tests or inventing phantom APIs. As Daniel Stenberg (curl) put it, it's becoming an accidental denial-of-service attack on maintainer attention.

Existing "AI detector" tools try to detect "AI-sounding English prose" in PR descriptions. I think that's the wrong layer:
1. LLM agents easily generate clean Markdown with bullet points.
2. It penalizes non-native English speakers who use an LLM just to proofread their notes.

I built SlopGate to inspect code and test invariants instead of English text, using Python's standard library `ast` in < 50ms:

1. Test Tamper Guard: Catches deleted asserts, tautology swaps (e.g. replacing `assert result == expected` with `assert result is not None` or `assert True`), and silent `try: ... except: pass` blocks in test files.
2. Phantom Symbol Detector: Catches uninstalled packages not in `pyproject.toml`/`requirements.txt` and hallucinated stdlib methods (like `json.loads_async`).
3. Repro Check: Flags PRs that touch core logic without adding or updating a test.

What it deliberately does NOT do:
- It doesn't run an LLM in your CI (0 token costs, no API keys, runs offline).
- It doesn't judge grammar or vocabulary.

You can try the interactive terminal simulation locally:
pip install slopgate && slopgate demo

Or run it as a composite GitHub Action:
uses: Shinraya-Tech-Labs/slopgate@main

Code: https://github.com/Shinraya-Tech-Labs/slopgate (Apache 2.0)

I'd genuinely love feedback from maintainers here on what AST rules or false-positive edge cases you'd like to see addressed.
```

---

## 2. Reddit `r/Python` — 100% Automod-Compliant Blueprint

> **Automod Rules for `r/Python`**:
> - Must use post flair: `Project`.
> - Must include the exact Markdown headings: `# What My Project Does`, `# Target Audience`, and `# Comparison`.

### Title:
```text
SlopGate: Zero-dependency AST shield to catch test tampering and phantom packages in PRs
```

### Post Body:
```markdown
GitHub Repo: https://github.com/Shinraya-Tech-Labs/slopgate

# What My Project Does

SlopGate is an open-source CLI tool and composite GitHub Action that audits git diffs using Python's standard library `ast` module in under 50 milliseconds.

It detects pull requests that pass CI dishonestly:
1. **Assertion Tampering**: Catches deleted `assert` statements or tautological downgrades (e.g., swapping `assert res.status == 200` to `assert res is not None` or `assert True`).
2. **Silent Failure Suppression**: Flags `try: ... except: pass` blocks introduced into test files.
3. **Phantom Packages**: Detects imported packages not declared in `pyproject.toml` or `requirements.txt`.
4. **Hallucinated Stdlib APIs**: Flags non-existent methods like `json.loads_async` or `os.mkdir_p`.

It includes an interactive terminal simulation so you can see it in action without configuring CI:
```bash
pip install slopgate
slopgate demo
```

# Target Audience

Open-source maintainers, library authors, and teams managing CI pipelines who want deterministic PR integrity checks without paying for LLM tokens or dealing with probabilistic "AI text detectors."

# Comparison

- **vs "AI Text Detectors" (Anti-Slop / LLM Graders)**: Tools that classify English descriptions fail on non-native speakers and miss actual code bugs. SlopGate ignores the prose and verifies AST code invariants only.
- **vs Linters (Ruff / Flake8)**: Linters check static syntax and style on individual files; SlopGate analyzes the semantic diff between branches to detect assertion weakening and missing reproduction tests.
- **Dependencies**: 0 external dependencies (uses standard library `ast`, `sys`, `pathlib`, `re`).

License: Apache 2.0
Feedback and PRs are welcome!
```

---

## 3. Twitter / X Viral Post

```text
Open-source maintainers are burning out from AI PR slop.

The sneaky part? Coding agents "fix" failing tests by:
1. Swapping `assert x == expected` to `assert x is not None`
2. Wrapping asserts in `except: pass`
3. Inventing fake APIs like `json.loads_async()`

We built SlopGate: an AST-based Code Integrity Shield. 🛡️

• 0 external dependencies (Python stdlib)
• < 50ms runtime (no LLM tokens billed)
• Zero false-positive drama (evaluates code, not English)

Try the interactive demo:
pip install slopgate && slopgate demo

GitHub: https://github.com/Shinraya-Tech-Labs/slopgate
```
