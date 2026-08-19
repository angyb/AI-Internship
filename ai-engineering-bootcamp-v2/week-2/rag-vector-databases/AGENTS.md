## Zearn Support Agent rules (Week 5 memory Path A)

### Durable memory: what we store
- A single per-user preference record scoped by anonymous `install_id`.
- Stored fields (nothing else): `role` (`student`, `teacher`, `parent`, or `admin`) and `grade_bands` (one or more of `Kindergarten` through `Grade 8`).

### Write gate (when we store)
- Memory is persisted only when the UI user clicks **Save preference**.
- The UI sends `confirmed_write: true` to `POST /memory`.
- The server rejects writes when `confirmed_write` is not true, and it ignores any non-`role` / non-`grade_band` content.

### Retrieval (when we read)
- Every `POST /agent` request loads memory for the same `install_id` and seeds it into the agent context via `format_memory_context()` in `memory_preferences.py` (role, grade bands, and a retrieval hint with the role search term).

### How the agent should use memory
- Memory may tailor response style (tone/reading level) and scope `search_zearn_doc` queries.
- Role → query phrase (append only one): `admin` → **for administrator**, `teacher` → for teacher, `parent` → for parent, `student` → for student. The tool strips other role terms from the query. Never include teacher, parent, student, or school district in the same query.
- Memory must not be treated as a factual source: Zearn facts still come from `search_zearn_doc` and/or `google_search_agent`.
- When preference memory is present, the agent includes one short, non-factual sentence near the start reflecting the grade band / role (to make recall obvious in the demo).

### Forgetting (when we delete)
- `DELETE /memory?install_id=...` (UI: **Forget preference**) removes the saved preference record.

### Existing citation rules (unchanged)
- Non-refusal answers must include a `**Sources:**` markdown bullet list with at least one markdown link.
- Web fallback answers must start with the configured fallback prefix and include at least one markdown link to a web-search URL.

