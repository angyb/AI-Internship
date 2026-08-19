## Zearn Support Agent rules (Week 5 memory Path A)

### Durable memory: what we store
- A single per-user preference record scoped by anonymous `install_id`.
- Stored fields (nothing else): `role` (`student`, `teacher`, or `admin`) and `grade_bands` (one or more of `Kindergarten` through `Grade 8`).

### Write gate (when we store)
- Memory is persisted only when the UI user clicks **Save preference**.
- The UI sends `confirmed_write: true` to `POST /memory`.
- The server rejects writes when `confirmed_write` is not true, and it ignores any non-`role` / non-`grade_band` content.

### Retrieval (when we read)
- Every `POST /agent` request loads memory for the same `install_id` and seeds it into the agent context as:
  `"User preference (durable memory): role=<role>; grade_bands=<comma-separated list>."`

### How the agent should use memory
- Memory is allowed only to tailor response style (tone/reading level).
- It must not be treated as a factual source: Zearn facts still come from `search_zearn_doc` and/or `google_search_agent`.
- When preference memory is present, the agent includes one short, non-factual sentence near the start reflecting the grade band / role (to make recall obvious in the demo).

### Forgetting (when we delete)
- `DELETE /memory?install_id=...` (UI: **Forget preference**) removes the saved preference record.

### Existing citation rules (unchanged)
- Non-refusal answers must include a `**Sources:**` markdown bullet list with at least one markdown link.
- Web fallback answers must start with the configured fallback prefix and include at least one markdown link to a web-search URL.

