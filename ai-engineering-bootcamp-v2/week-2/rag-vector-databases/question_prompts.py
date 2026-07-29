"""Type-specific step 1 (fact extraction) and step 2 (grounding) prompt templates."""

from __future__ import annotations

from string import Template

from question_classifier import QuestionType

# Shared substitution keys: $context, $question, $extracted_facts,
# $EXTRACTION_SCOPE_RULES, $FIDELITY_RULES, $VERBOSITY_RULES, $CITATION_RULES

_FACT_EXTRACTION: dict[QuestionType, Template] = {
    "how_to": Template("""\
Read ALL retrieved context chunks and extract facts needed to answer this how-to question.

Group facts under these headings (omit if nothing applies):
- Prerequisites: account type, permissions, or setup required before starting
- Alternate paths: different ways to accomplish the goal (e.g. class code vs rostering) — list each path separately
- Steps: ordered actions in sequence (preserve step numbers when present in context)
- Limits and notes: caps, eligibility, warnings, or post-step instructions

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Include alternate paths BEFORE main steps when the context mentions them.
- Preserve specific numbers, UI labels, and menu names exactly.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "research": Template("""\
Read ALL retrieved context chunks and extract research and evidence facts.

Group facts under these headings (omit if nothing applies):
- Term / acronym: define any assessment name, acronym, or study term (e.g. what LEAP stands for)
- Study context: location, population, timeframe, or program described
- Findings: specific outcomes, metrics, percentages, or score changes
- Methodology: how the study was conducted, if stated

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Prefer the most specific numbers and named studies from the context.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "report": Template("""\
Read ALL retrieved context chunks and extract facts about reports, alerts, or dashboards.

Group facts under these headings (omit if nothing applies):
- What it is: purpose of the report or alert
- Trigger / cause: specific events that generate the alert or populate the report (prefer precise wording, e.g. "three Boosts")
- What it shows: metrics, columns, or student information displayed
- Where to find it: navigation path, menu, or UI location

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Distinguish similarly named reports when the context describes multiple.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "comparison": Template("""\
Read ALL retrieved context chunks and extract facts for comparing options (accounts, plans, features).

Group facts under these headings (omit if nothing applies):
- Option A: name and key facts (cost, limits, eligibility)
- Option B: name and key facts (cost, limits, eligibility)
- Other options: any additional tiers or paths mentioned
- Key differences: explicit contrasts stated in the context

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Include numeric limits (e.g. student caps) and free vs paid distinctions.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "definition": Template("""\
Read ALL retrieved context chunks and extract facts that define or explain the concept asked about.

Group facts under these headings (omit if nothing applies):
- Definition: what the thing is
- Trigger / cause: specific events or conditions that produce an outcome (prefer precise wording)
- Conditions / limits: eligibility rules, numeric limits, alternative paths
- Location / where seen: reports, UI locations, product surfaces

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Read every chunk before writing; combine distinct facts from different chunks.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "affirmation": Template("""\
Read ALL retrieved context chunks and extract facts that support a yes/no question about design, science, or approach.

Group facts under these headings (omit if nothing applies):
- Affirmation: direct yes/no support from the context
- Mechanism / approach: specific pedagogical or design phrases (e.g. concrete → pictorial → abstract, CPA progression)
- Evidence: research basis, design principles, or stated rationale

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Capture exact pedagogical phrases from the context verbatim when present.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "integration": Template("""\
Read ALL retrieved context chunks and extract facts about rostering, SSO, or third-party integrations.

Group facts under these headings (omit if nothing applies):
- Integration type: Clever, ClassLink, OneRoster, spreadsheet, etc.
- Prerequisites: admin setup, permissions, or account requirements
- Setup steps: ordered configuration or sync steps
- Troubleshooting notes: common issues or limitations mentioned

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "checklist_orientation": Template("""\
Read ALL retrieved context chunks and extract orientation or getting-started facts.

Group facts under these headings (omit if nothing applies):
- Audience: who this orientation is for (teacher, admin, school lead)
- Checklist items: ordered tasks or first steps
- Resources: linked guides, PDFs, or follow-up actions
- Tips: best practices or reminders from the context

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Preserve checklist order when the context uses numbered or bulleted lists.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "list_features": Template("""\
Read ALL retrieved context chunks and extract a list of items, features, or names requested.

Group facts under these headings (omit if nothing applies):
- Items: each distinct feature, name, or item (names only unless descriptions are requested)
- Groupings: categories or sections if the context organizes items

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Extract every relevant item from all chunks; do not summarize away individual names.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "parent_family": Template("""\
Read ALL retrieved context chunks and extract facts for parents, families, or home use.

Group facts under these headings (omit if nothing applies):
- What families can do: actions available to parents or guardians
- How to: steps for family-specific tasks (class codes, progress, login)
- Limits: what families cannot access or account restrictions

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "troubleshooting": Template("""\
Read ALL retrieved context chunks and extract troubleshooting facts.

Group facts under these headings (omit if nothing applies):
- Symptom: the problem described or implied by the question
- Likely causes: conditions or settings mentioned in the context
- Resolution steps: ordered fixes or workarounds
- Escalation: when to contact support or try alternate paths

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "yes_no": Template("""\
Read ALL retrieved context chunks and extract facts that answer a yes/no question.

Group facts under these headings (omit if nothing applies):
- Direct answer: facts that support yes, no, or conditional answers
- Conditions: when the answer differs (account type, settings, grade level)
- Supporting detail: brief context that explains the answer

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "requirements": Template("""\
Read ALL retrieved context chunks and extract technology and compatibility requirements.

Group facts under these headings (omit if nothing applies):
- Supported devices: tablets, computers, operating systems
- Browsers and versions: supported or unsupported browsers
- Network / bandwidth: connectivity requirements
- Other requirements: accessories, settings, or restrictions

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "permissions": Template("""\
Read ALL retrieved context chunks and extract facts about roles, permissions, and access levels.

Group facts under these headings (omit if nothing applies):
- Role definitions: admin, teacher, co-teacher, staff, etc.
- Capabilities: what each role can and cannot do
- Setup: how to assign or change roles

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "policy": Template("""\
Read ALL retrieved context chunks and extract policy and privacy facts.

Group facts under these headings (omit if nothing applies):
- Policy summary: what the policy covers
- Data practices: collection, sharing, subprocessors
- User rights or compliance: FERPA, GDPR, or stated commitments

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "navigation": Template("""\
Read ALL retrieved context chunks and extract navigation and location facts.

Group facts under these headings (omit if nothing applies):
- Location: where in the product or site to find the feature or report
- Navigation steps: click path or menu sequence
- Related pages: alternate entry points mentioned

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Preserve exact menu and button names from the context.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
    "general": Template("""\
Read ALL retrieved context chunks below and extract every distinct fact that helps answer the question.

Group facts under these headings (omit a heading if nothing applies):
- Definition: what the thing is
- Trigger / cause: specific events or conditions that produce an outcome (prefer precise wording, e.g. "three Boosts" over "multiple times")
- Conditions / limits: eligibility rules, numeric limits, alternative paths (e.g. class codes, student caps)
- Location / where seen: reports, UI locations, product surfaces

Rules:
- Use ONLY information from the context chunks. Do not infer or add outside knowledge.
- Read every chunk before writing; combine distinct facts from different chunks.
- When chunks disagree, include the most specific version of each fact.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use bullet points under each heading.

Retrieved context:
$context

Question: $question

Extracted facts:"""),
}

_GROUNDING: dict[QuestionType, Template] = {
    "how_to": Template("""\
Answer the how-to question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Output numbered steps when the question asks how to do something; preserve UI labels from the context.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "research": Template("""\
Answer the research or evidence question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Define any acronym or assessment term in the first sentence when the question asks "what is X".
- Include specific findings, populations, or metrics when present in extracted facts.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "report": Template("""\
Answer the report or alert question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- State what it is and its trigger/cause using precise wording from the context (e.g. "three Boosts" not "multiple times").
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "comparison": Template("""\
Answer the comparison question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Lead with a direct answer if the question asks yes/no or "which is free".
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "definition": Template("""\
Answer the definition question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Prefer the most specific wording from extracted facts (e.g. "three Boosts" not "multiple times").
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "affirmation": Template("""\
Answer the yes/no or design-rationale question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Begin with a clear yes or no when the question asks "is" or "does".
- Include the specific mechanism or pedagogical phrase from the context verbatim when present (e.g. concrete → pictorial → abstract).
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "integration": Template("""\
Answer the integration or rostering question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Include prerequisites and ordered setup steps when present.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "checklist_orientation": Template("""\
Answer the orientation or checklist question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use a numbered checklist or bullet list preserving order from extracted facts.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "list_features": Template("""\
Answer the list question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Follow the requested format: if the question asks for names only, list names without descriptions.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "parent_family": Template("""\
Answer the parent or family question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use plain language suitable for families; include steps when the question is procedural.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "troubleshooting": Template("""\
Answer the troubleshooting question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Present resolution steps in order; state the symptom and fix clearly.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "yes_no": Template("""\
Answer the yes/no question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Lead with yes, no, or it depends — then brief supporting detail from extracted facts.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "requirements": Template("""\
Answer the requirements question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- List supported devices, browsers, and network requirements when present.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "permissions": Template("""\
Answer the permissions question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Clarify what each role can and cannot do when the question asks about access.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "policy": Template("""\
Answer the policy question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Summarize policy points factually without legal interpretation beyond the extracted facts.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "navigation": Template("""\
Answer the navigation question using ONLY the extracted facts below.

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Give the exact navigation path or menu sequence from extracted facts.
- If the extracted facts are insufficient, refuse clearly and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
    "general": Template("""\
Answer the question using ONLY the extracted facts below (derived from retrieved context).

Rules:
- Use ONLY facts listed under "Extracted facts". Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- If the extracted facts are insufficient to answer the question, refuse clearly in your answer \
and set sources_needed to true.

Extracted facts:
$extracted_facts

Question: $question"""),
}

_SINGLE_STEP: dict[QuestionType, Template] = {
    "how_to": Template("""\
Answer the how-to question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Output numbered steps when the question asks how to do something; preserve UI labels from the context.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "research": Template("""\
Answer the research or evidence question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Define acronyms or assessment terms in the first sentence when asked "what is X".
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "report": Template("""\
Answer the report or alert question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- State what it is and its trigger/cause using precise wording from the context (e.g. "three Boosts" not "multiple times").
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "comparison": Template("""\
Answer the comparison question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Lead with a direct answer for yes/no or "which is free" questions.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "definition": Template("""\
Answer the definition question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Prefer the most specific wording from the context (e.g. "three Boosts" not "multiple times").
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "affirmation": Template("""\
Answer the yes/no or design-rationale question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Begin with yes or no; include specific pedagogical phrases from the context verbatim when present (e.g. concrete → pictorial → abstract).
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "integration": Template("""\
Answer the integration or rostering question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Include prerequisites and ordered setup steps when present.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "checklist_orientation": Template("""\
Answer the orientation or checklist question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Use a numbered checklist preserving order from context.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "list_features": Template("""\
Answer the list question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- If the question asks for names only, list names without descriptions.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "parent_family": Template("""\
Answer the parent or family question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "troubleshooting": Template("""\
Answer the troubleshooting question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Present resolution steps in order.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "yes_no": Template("""\
Answer the yes/no question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Lead with yes, no, or it depends — then brief supporting detail.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "requirements": Template("""\
Answer the requirements question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- List supported devices, browsers, and network requirements when present.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "permissions": Template("""\
Answer the permissions question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Clarify role capabilities when asked about access levels.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "policy": Template("""\
Answer the policy question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "navigation": Template("""\
Answer the navigation question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- Give the exact navigation path from context.
- If the context is insufficient, refuse clearly and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
    "general": Template("""\
Answer the question using ONLY the retrieved context below.

Rules:
- Use ONLY facts from the context chunks. Do not use outside knowledge.
$EXTRACTION_SCOPE_RULES
$FIDELITY_RULES
$VERBOSITY_RULES
$CITATION_RULES
- If the context is insufficient to answer the question, refuse clearly in your answer \
and set sources_needed to true.

Retrieved context:
$context

Question: $question"""),
}


def get_fact_extraction_template(question_type: QuestionType) -> Template:
    return _FACT_EXTRACTION.get(question_type, _FACT_EXTRACTION["general"])


def get_grounding_template(question_type: QuestionType) -> Template:
    return _GROUNDING.get(question_type, _GROUNDING["general"])


def get_single_step_template(question_type: QuestionType) -> Template:
    return _SINGLE_STEP.get(question_type, _SINGLE_STEP["general"])
