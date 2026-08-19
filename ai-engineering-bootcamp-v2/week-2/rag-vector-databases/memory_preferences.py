"""Allowed durable memory preference values (Week 5 Path A)."""

MEMORY_ROLE_OPTIONS = ["student", "teacher", "admin"]
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

# Terms to include in search_zearn_doc queries when durable memory is present.
MEMORY_ROLE_SEARCH_TERMS = {
    "admin": "administrators",
    "teacher": "teachers",
    "student": "students",
}


def format_memory_context(role: str, grade_bands: list[str]) -> str:
    """Build the seeded memory string injected before each agent turn."""
    bands = ", ".join(grade_bands)
    search_term = MEMORY_ROLE_SEARCH_TERMS.get(role.strip().lower(), role)
    return (
        f"User preference (durable memory): role={role}; grade_bands={bands}. "
        f'Retrieval hint: include "{search_term}" in search_zearn_doc queries '
        "for this user (include grade bands when relevant)."
    )
