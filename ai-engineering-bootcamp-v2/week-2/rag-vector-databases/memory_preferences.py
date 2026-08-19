"""Allowed durable memory preference values (Week 5 Path A)."""

MEMORY_ROLE_OPTIONS = ["student", "teacher", "parent", "admin"]
MEMORY_GRADE_BAND_OPTIONS = [
    "Kindergarten",
    "Grade 1",
    "Grade 2",
    "Grade 3",
    "Grade 4",
    "Grade 5",
    "Grade 6",
    "Grade 7",
    "Grade 8",
]

# Role phrase appended to search_zearn_doc queries when durable memory is present.
MEMORY_ROLE_SEARCH_PHRASES = {
    "admin": "for administrator",
    "teacher": "for teacher",
    "student": "for student",
    "parent": "for parent",
}


def role_search_phrase(role: str) -> str | None:
    return MEMORY_ROLE_SEARCH_PHRASES.get(role.strip().lower())


def format_memory_context(role: str, grade_bands: list[str]) -> str:
    """Build the seeded memory string injected before each agent turn."""
    bands = ", ".join(grade_bands)
    phrase = role_search_phrase(role)
    hint = (
        f'Retrieval hint: append ONLY "{phrase}" for role scoping in '
        "search_zearn_doc queries. Do not include other roles (teacher, parent, "
        "student, school district, etc.) in the query."
        if phrase
        else ""
    )
    return (
        f"User preference (durable memory): role={role}; grade_bands={bands}. "
        f"{hint}"
    ).strip()
