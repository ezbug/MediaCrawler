# Installed reply runtime patches

The reply runtime lives in the user Skill, outside this repository. These patches
record the source changes required by the repository's safety regression tests.
They contain no campaign data or credentials. Do not apply a patch to a different
runtime revision without reviewing its source and rerunning the safety tests.

## XHS rich text

- Patch: `xhs-rich-text.patch`
- Before SHA-256: `a2275e027efd4b696a183a3c89eaf277b7d927524590a5a366f8d6ddedec9292`
- After SHA-256: `638d40aa6aa0da4a9b9b5802233a2a975d7e31293b64502aedf2b3235e54dd2a`
- Runtime: `~/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs`

The locator reconstructs emoji images only from unique mappings supplied by the
current page. Publication checks require the complete reconstructed target quote
to equal the native comment content, in addition to exact comment/user IDs and
the native reply relationship. Unknown images and ambiguous mappings fail closed.
Plain rendered quotes from older collections remain distinguishable from complete
native quotes; image tokens are not removed to obtain a match.

Validation:

```sh
node --test tests/auto_reply_safety.test.mjs tests/search_relevance.test.mjs tests/zigo_search.test.mjs
```

Before a manual application, verify the before hash, save the existing runtime,
and dry-run the patch with `patch --dry-run`. Verify the after hash and tests after
application. Applying this patch never starts a browser or submits a reply.
