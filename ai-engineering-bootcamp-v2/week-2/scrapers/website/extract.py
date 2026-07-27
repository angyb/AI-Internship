"""Shared HTML → markdown extraction for about.zearn.org pages."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import html2text
import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

USER_AGENT = "ZearnRAGBot/1.0 (internal content indexing; contact: zearn.org)"
MIN_BODY_WORDS = 20
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# Standalone button/link labels to drop (not prose).
EXCLUDED_PATH_PREFIXES = ("/webinar-recordings/",)
EXCLUDED_EXACT_PATHS = frozenset({"/sitemap"})

RESEARCH_BOILERPLATE_HEADINGS = {
    "at a glance",
    "share this article",
    "related articles",
}

RESEARCH_BOILERPLATE_LINES = {
    "+",
    "notes",
    "written by",
    "join the conversation",
    "share this article",
}

PRESS_RELEASE_BOILERPLATE_HEADINGS = {
    "related articles",
    "notes",
}

ABOUT_ZEARN_BOILERPLATE_MARKER = "501(c)(3) nonprofit educational organization behind zearn math"

LEARNING_ACCELERATION_CTA_BODY = (
    "learn more about how zearn can support learning acceleration in your school or district."
)

GET_STARTED_CTA_BODY = (
    "create a free account or reach out to learn more about using zearn programmatically in your school or district."
)

SUMMER_MATH_CTA_MARKER = "to get access to all content"

SPANISH_CONTENT_THRESHOLD = 0.95

ENGLISH_INDICATOR_WORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before being below between both but by can did do does doing done down during each few for from further had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not of off on once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too under until up very was we were what when where which while who whom why with you your yours yourself yourselves all also any back big both call came come could day did different does don't each end even every find first follow found get give go good great group hand help high home important keep kind know large last left life line little long look made make man many may men might much must name need new next number old one open part people place point put right said same say see set she should show small so some still such take tell than that their them then there these they thing think this those thought three through time today together too two under until up us use very want water way well went were what when where which while who will with word work world would write year years student students teacher teachers school schools learning lessons math family families support resources help children child progress goals studies shows complete weekly daily instruction improvements motivate communicate information english spanish explore learn commitment make mistakes encourage best integrated overcome problems difficult free account district programmatically reach started get create using use used using account accounts digital lesson lessons grade grades content platform teacher teaching teach taught curriculum curricula research report data access provide provides provided including include included within without across through during after before over under between against according available based become becomes became becoming being believe believed build builds built continue continues continued different following follows followed given gives given going help helps helped high higher highest improve improves improved including increase increases increased individual individuals offer offers offered program programs provide provides providing public quality receive receives received require requires required result results resulting serve serves service services state states support supports supported system systems understand understands understanding use uses used using work works working world would year years your yours""".split()
)

NEUTRAL_WORDS = frozenset(
    {"zearn", "math", "z", "org", "pdf", "http", "https", "com", "www", "edreports", "edweek", "youtube", "facebook", "twitter", "linkedin"}
)

STANDALONE_CTA_LINES = {
    "text link",
    "explore a lesson",
    "explore the full evidence base",
    "why zearn math",
    "read our privacy policy",
    "family resource hub",
    "using zearn math for impact",
    "create a free account",
    "contact us",
    "sign up",
    "log in",
    "get started",
    "donate",
}


def _normalize_block(text: str) -> str:
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff\ufe0f]", "", text)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return re.sub(r"\s+", " ", text.strip()).lower()


def _is_learning_acceleration_cta(text: str) -> bool:
    return LEARNING_ACCELERATION_CTA_BODY in _normalize_block(text)


def _is_about_zearn_boilerplate(block: str) -> bool:
    norm = _normalize_block(block)
    return (
        "about zearn" in norm
        and ABOUT_ZEARN_BOILERPLATE_MARKER in norm
        and "annao@zearn.org" in norm
    )


def is_mostly_spanish(text: str, threshold: float = SPANISH_CONTENT_THRESHOLD) -> bool:
    """True when text is at least threshold Spanish by English-function-word density."""
    words = re.findall(r"[a-záéíóúüñ']+", text.lower())
    if len(words) < 20:
        return False
    english = 0
    counted = 0
    for word in words:
        if word in NEUTRAL_WORDS:
            continue
        counted += 1
        if word in ENGLISH_INDICATOR_WORDS:
            english += 1
    if counted == 0:
        return False
    return (1 - english / counted) >= threshold


def is_excluded_path(path: str) -> bool:
    """Paths we never scrape (e.g. webinar recordings, Spanish pages, nav indexes)."""
    if path in EXCLUDED_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES):
        return True
    if "espanol" in path.lower():
        return True
    return False

TABBED_PAGE_CHECKS: dict[str, list[str]] = {
    "/how-zearn-math-works": [
        "procedural fluency",
        "TEACHERS",
        "supports families",
        "districts",
    ],
}


def parse_sitemap(xml_text: str) -> dict[str, str | None]:
    """Return {url: lastmod} from sitemap XML."""
    soup = BeautifulSoup(xml_text, "lxml-xml")
    entries: dict[str, str | None] = {}
    for url_tag in soup.find_all("url"):
        loc = url_tag.find("loc")
        if not loc or not loc.text:
            continue
        lastmod_tag = url_tag.find("lastmod")
        lastmod = lastmod_tag.text.strip() if lastmod_tag and lastmod_tag.text else None
        entries[loc.text.strip()] = lastmod
    if entries:
        return entries
    for loc in soup.find_all("loc"):
        if loc.text:
            entries[loc.text.strip()] = None
    return entries


def url_to_doc_id(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.replace("/", "-") if path else "index"


def url_to_path(url: str) -> str:
    path = urlparse(url).path or "/"
    return path if path.startswith("/") else f"/{path}"


def url_to_section(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return "home"
    return path.split("/")[0]


def clean_title(raw: str) -> str:
    title = re.sub(r"\s+", " ", raw).strip()
    for sep in (" | ", " - ", " — "):
        if sep in title:
            title = title.split(sep)[0].strip()
            break
    return title


def get_page_metadata(soup: BeautifulSoup, url: str, lastmod: str | None) -> dict[str, Any]:
    title_tag = soup.find("title")
    raw_title = title_tag.get_text(strip=True) if title_tag else url_to_doc_id(url)
    desc_tag = soup.find("meta", attrs={"name": "description"})
    description = desc_tag.get("content", "").strip() if desc_tag else ""
    scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    parsed = urlparse(url)
    return {
        "doc_id": url_to_doc_id(url),
        "source_url": url,
        "title": clean_title(raw_title),
        "source_site": parsed.netloc,
        "source_type": "website",
        "language": "en",
        "path": url_to_path(url),
        "section": url_to_section(url),
        "description": description,
        "lastmod": lastmod,
        "scraped_at": scraped_at,
    }


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().upper()


def _find_feature_body_slots(section: Tag) -> list[Tag]:
    container = section
    for _ in range(8):
        if container.parent is None:
            break
        container = container.parent
        body = container.select_one('[class*="feature_body"]:not([class*="feature_body-slot"])')
        if body:
            slots = body.select('[class*="feature_body-slot"]')
            if slots:
                return slots
    return []


def label_feature_tabs(main: Tag) -> int:
    """Insert tab headings for Zearn feature-bar components."""
    labeled = 0
    for section in main.select(".zearn-with-design-system--feature-bar_section"):
        links = section.select('[class*="feature-bar_link"]')
        labels = [_normalize_label(link.get_text(" ", strip=True)) for link in links]
        slots = _find_feature_body_slots(section)
        for label, slot in zip(labels, slots):
            heading = main.new_tag("h2")
            heading["class"] = ["scraper-tab-label"]
            heading.string = f"Tab: {label}"
            slot.insert(0, heading)
            labeled += 1
    return labeled


def label_webflow_tabs(main: Tag) -> int:
    """Insert tab headings for standard Webflow w-tabs components."""
    labeled = 0
    for tabs in main.select(".w-tabs"):
        links = tabs.select(".w-tab-link")
        panes = tabs.select(".w-tab-pane")
        for link, pane in zip(links, panes):
            label = _normalize_label(link.get_text(" ", strip=True))
            if not label:
                continue
            heading = main.new_tag("h2")
            heading["class"] = ["scraper-tab-label"]
            heading.string = f"Tab: {label}"
            pane.insert(0, heading)
            labeled += 1
    return labeled


def _is_merge_separator(el: Tag | NavigableString) -> bool:
    """Elements allowed between split headings of the same level (e.g. decorative images)."""
    if isinstance(el, NavigableString):
        return not str(el).strip()
    if el.name in ("img", "br", "svg"):
        return True
    if el.name in HEADING_TAGS:
        return False
    if el.name in ("div", "span"):
        for child in el.children:
            if isinstance(child, NavigableString):
                if str(child).strip():
                    return False
                continue
            if not isinstance(child, Tag) or not _is_merge_separator(child):
                return False
        return True
    return False


def _topmost_tags(tags: list[Tag]) -> list[Tag]:
    return [tag for tag in tags if not any(tag is not other and tag in other.descendants for other in tags)]


def _is_within_tag(node: Tag | NavigableString, tag: Tag) -> bool:
    if node is tag:
        return True
    parent = node.parent if hasattr(node, "parent") else None
    while parent:
        if parent is tag:
            return True
        parent = parent.parent
    return False


def _wrapper_contains_only_split_heading(el: Tag, level: str) -> Tag | None:
    """Return inner heading when a wrapper holds only one same-level h# plus decorations."""
    if el.name not in ("div", "span"):
        return None
    headings = el.find_all(level, recursive=True)
    if len(headings) != 1:
        return None
    h = headings[0]
    for child in el.descendants:
        if _is_within_tag(child, h):
            continue
        if isinstance(child, NavigableString):
            if str(child).strip():
                return None
            continue
        if isinstance(child, Tag) and not _is_merge_separator(child):
            return None
    return h


def _find_mergeable_split_heading(h_first: Tag, level: str) -> tuple[Tag | None, list[Tag]]:
    """Find a same-level heading split from h_first by images/decorations only."""
    removable: list[Tag] = []
    h_second: Tag | None = None

    for el in h_first.next_elements:
        if el is h_first:
            continue
        if isinstance(el, Tag):
            if el.name in HEADING_TAGS:
                if el.name == level:
                    h_second = el
                break
            if h_first in el.descendants or el is h_first.parent:
                continue
            inner_h = _wrapper_contains_only_split_heading(el, level)
            if inner_h is not None:
                h_second = inner_h
                removable.append(el)
                break
            if not _is_merge_separator(el):
                return None, []
            if el.name in ("img", "br", "svg") or (
                el.name in ("div", "span") and not el.find(list(HEADING_TAGS))
            ):
                removable.append(el)
            continue
        if isinstance(el, NavigableString):
            parent = el.parent
            if parent is h_first or (parent and h_first in parent.parents):
                continue
            if str(el).strip():
                return None, []
            continue

    if h_second is None:
        return None, []
    return h_second, _topmost_tags(removable)


def merge_split_headings(main: Tag) -> None:
    """Combine same-level headings split by decorative images (common Webflow pattern)."""
    merged = True
    while merged:
        merged = False
        for level in HEADING_TAGS:
            for h_first in main.find_all(level):
                if not h_first.parent:
                    continue
                h_second, removable = _find_mergeable_split_heading(h_first, level)
                if h_second is None:
                    continue
                part1 = h_first.get_text(" ", strip=True)
                part2 = h_second.get_text(" ", strip=True)
                combined = re.sub(r"\s+", " ", f"{part1} {part2}".replace("\xa0", " ")).strip()
                h_first.clear()
                h_first.string = combined
                h_second.decompose()
                for el in removable:
                    if el.parent:
                        el.decompose()
                merged = True
                break
            if merged:
                break


def remove_empty_headings(main: Tag) -> None:
    """Drop heading tags with no visible text."""
    for level in HEADING_TAGS:
        for heading in main.find_all(level):
            if not heading.get_text(strip=True):
                heading.decompose()


def _is_hidden_element(el: Tag) -> bool:
    """True for Webflow/CSS hidden nodes (display:none or hide/hidden classes)."""
    style = el.get("style") or ""
    if re.search(r"display\s*:\s*none", style, re.IGNORECASE):
        return True
    for cls in el.get("class") or []:
        lower = cls.lower()
        if lower in {"hide", "hidden", "w-condition-invisible"}:
            return True
        if lower.startswith("hide-") or lower.endswith("-hide"):
            return True
        if lower.startswith("hidden-") or lower.endswith("-hidden"):
            return True
    return False


def remove_hidden_elements(main: Tag) -> None:
    """Remove hidden responsive duplicates and display:none blocks from the DOM."""
    hidden = [el for el in main.find_all(True) if _is_hidden_element(el)]
    hidden_set = set(hidden)
    for el in hidden:
        if any(isinstance(parent, Tag) and parent in hidden_set for parent in el.parents):
            continue
        el.decompose()


def prepare_main_content(main: Tag) -> None:
    """Remove non-content elements and normalize text before markdown conversion."""
    remove_empty_headings(main)
    remove_hidden_elements(main)

    # Breadcrumb navigation (e.g. Home > Texas) is not article content.
    for el in main.select("nav.breadcrumbs_component, .breadcrumbs_component"):
        el.decompose()

    # In-page navigation sidebars (e.g. terms/privacy table of contents).
    for el in main.select(".terms-sidebar_wrapper"):
        el.decompose()

    # Learning acceleration footer CTA tiles.
    for el in main.select(".section-insights-cta, .blue-cta-tile-wrapper, .blue-cta-tile"):
        if _is_learning_acceleration_cta(el.get_text(" ", strip=True)):
            el.decompose()

    for el in main.select(".get-started-wrapper2"):
        el.decompose()

    for el in main.select(
        "script, style, svg, img, video, picture, source, iframe, "
        "[class*='background-video'], [class*='w-background-video']"
    ):
        el.decompose()

    # Tab navigation labels only — body slots keep ## Tab: headings.
    for el in main.select('[class*="feature-bar_link"]'):
        el.decompose()

    for el in main.select(".w-tab-menu, .w-tab-link"):
        el.decompose()

    # Standalone buttons and CTA link blocks (remove whole containers).
    for el in main.select(
        "a.w-button, a.v1_button, button, "
        "[class*='link-block'], [class*='button-row'], [class*='button-wrapper'], "
        "a.text-link, a[class*='text-link']"
    ):
        el.decompose()

    # Divs/spans that only contain CTA-style text (no paragraph content).
    for el in main.find_all(["div", "span", "p"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.find(["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "article"]):
            continue
        norm = re.sub(r"\s+", " ", text).strip().lower()
        if norm in STANDALONE_CTA_LINES and len(el.find_all(["div", "section"])) <= 1:
            el.decompose()

    for br in main.find_all("br"):
        br.replace_with(" ")

    # Inline links → plain text; card links → unwrap; standalone CTAs → remove.
    for anchor in main.find_all("a"):
        if _should_unwrap_link(anchor):
            anchor.unwrap()
        elif _is_inline_link(anchor):
            anchor.replace_with(anchor.get_text(" ", strip=True))
        else:
            anchor.decompose()

    # Bold/strong and italic/emphasis → plain text.
    for tag in main.find_all(["strong", "b", "em", "i"]):
        tag.unwrap()

    # Drop empty wrappers left behind.
    for el in main.find_all(class_=lambda c: c and "w-embed" in c):
        if not el.get_text(strip=True):
            el.decompose()


def _should_unwrap_link(anchor: Tag) -> bool:
    """Keep structured content from card-style links (headings + descriptions)."""
    if anchor.find(list(HEADING_TAGS)):
        return True
    classes = " ".join(anchor.get("class") or [])
    return any(token in classes for token in ("learn-more-item", "material-item", "featured-item"))


def _is_inline_link(anchor: Tag) -> bool:
    """True when the link sits inside running prose (keep text only)."""
    parent = anchor.parent
    if parent is None:
        return False
    if parent.name in ("p", "li", "span", "em", "i", "h1", "h2", "h3", "h4", "h5", "h6"):
        return True
    if parent.name in ("div", "section", "article"):
        parent_text = parent.get_text(" ", strip=True)
        anchor_text = anchor.get_text(" ", strip=True)
        if parent_text and anchor_text and parent_text != anchor_text:
            return True
    return False


def html_to_markdown(html_fragment: str) -> str:
    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.ignore_links = True
    converter.ignore_images = True
    converter.single_line_break = False
    md = converter.handle(html_fragment)
    return clean_markdown(md)


def normalize_list_indentation(md: str) -> str:
    """Dedent sibling list items so marker spacing is not treated as nesting."""
    list_item_re = re.compile(r"^(\s*)([*\-+]|\d+\.)\s")
    lines = md.splitlines()
    output: list[str] = []
    group: list[str] = []

    def flush_group() -> None:
        nonlocal group
        if not group:
            return
        indents = [
            len(match.group(1))
            for line in group
            if (match := list_item_re.match(line))
        ]
        if indents:
            min_indent = min(indents)
            for line in group:
                match = list_item_re.match(line)
                output.append(line[min_indent:] if match else line)
        else:
            output.extend(group)
        group = []

    for line in lines:
        if list_item_re.match(line):
            group.append(line)
        else:
            flush_group()
            output.append(line)
    flush_group()
    return "\n".join(output)


def clean_markdown(md: str) -> str:
    """Post-process markdown to match content-extraction rules."""
    md = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    md = re.sub(r"__(.+?)__", r"\1", md)
    md = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\[\s*\]", "", md)
    md = re.sub(r"^\s*Text Link\s*$", "", md, flags=re.M)
    lines = []
    for line in md.splitlines():
        stripped = line.strip()
        if re.match(r"^#+\s*$", stripped):
            continue
        norm = re.sub(r"\s+", " ", stripped).lower()
        if norm in STANDALONE_CTA_LINES:
            continue
        lines.append(line.rstrip())
    md = "\n".join(lines)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = normalize_list_indentation(md)
    return md.rstrip()


def _is_tab_label_line(line: str) -> bool:
    """Standalone tab nav label fragments (e.g. 'build fluency')."""
    norm = re.sub(r"\s+", " ", line.strip().lower())
    tab_labels = {
        "build fluency", "learn concepts", "solve math problems",
        "write your work", "get real-time support", "show mastery",
        "teachers", "families", "systems",
    }
    return norm in tab_labels


def dedupe_markdown(markdown: str) -> tuple[str, int]:
    """Remove consecutive duplicate blocks (Webflow responsive copies)."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    deduped: list[str] = []
    removed = 0
    prev_norm: str | None = None

    for block in blocks:
        norm = re.sub(r"\s+", " ", block.strip()).lower()
        if not norm:
            continue
        if _is_tab_label_line(block):
            removed += 1
            continue
        if norm == prev_norm:
            removed += 1
            continue
        deduped.append(block.strip())
        prev_norm = norm

    return "\n\n".join(deduped), removed


def strip_research_boilerplate(markdown: str, path: str) -> str:
    """Remove research article chrome (At a Glance, share widgets, related articles)."""
    if not path.startswith("/research/"):
        return markdown

    blocks = re.split(r"\n\s*\n", markdown.strip())
    cleaned: list[str] = []
    skip_remaining = False

    for block in blocks:
        if skip_remaining:
            continue

        lines = block.strip().split("\n")
        first = lines[0].strip()

        if first.startswith("# ") and not first.startswith("##"):
            cleaned.append(block.strip())
            continue

        if first.startswith("##"):
            heading = re.sub(r"^#+\s*", "", first).strip().lower()
            if heading in RESEARCH_BOILERPLATE_HEADINGS:
                if heading == "related articles":
                    skip_remaining = True
                continue
            if heading == "":
                continue

        norm = re.sub(r"\s+", " ", block.strip()).lower()
        if norm in RESEARCH_BOILERPLATE_LINES:
            continue

        # Drop short subtitle duplicates and chrome; keep only substantial article body.
        if len(block.split()) < 80:
            continue

        cleaned.append(block.strip())

    return "\n\n".join(cleaned)


def strip_learning_acceleration_cta(markdown: str) -> str:
    """Remove the 'Let's do this' learning acceleration CTA block."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    cleaned: list[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        heading = re.sub(r"^#+\s*", "", block.strip()).strip()
        heading_norm = _normalize_block(heading)
        block_norm = _normalize_block(block)

        if heading_norm == "let's do this" and i + 1 < len(blocks):
            next_norm = _normalize_block(blocks[i + 1])
            if LEARNING_ACCELERATION_CTA_BODY in next_norm:
                i += 2
                continue

        if block_norm == LEARNING_ACCELERATION_CTA_BODY:
            i += 1
            continue

        cleaned.append(block.strip())
        i += 1

    return "\n\n".join(cleaned)


def strip_get_started_cta(markdown: str) -> str:
    """Remove the footer 'Get started' account CTA block."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    cleaned: list[str] = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        heading = re.sub(r"^#+\s*", "", block.strip()).strip()
        heading_norm = _normalize_block(heading)
        block_norm = _normalize_block(block)

        if heading_norm == "get started" and i + 1 < len(blocks):
            next_norm = _normalize_block(blocks[i + 1])
            if GET_STARTED_CTA_BODY in next_norm:
                i += 2
                continue

        if block_norm == GET_STARTED_CTA_BODY:
            i += 1
            continue

        cleaned.append(block.strip())
        i += 1

    return "\n\n".join(cleaned)


def strip_summer_math_cta_fragment(markdown: str) -> str:
    """Remove hidden summer-math CTA copy if it slips through HTML cleanup."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    cleaned: list[str] = []
    for block in blocks:
        norm = _normalize_block(block)
        if SUMMER_MATH_CTA_MARKER in norm and "spring/summer 2023" in norm:
            continue
        cleaned.append(block.strip())
    return "\n\n".join(cleaned)


def strip_press_release_boilerplate(markdown: str, path: str) -> str:
    """Remove press release footer chrome (About Zearn blurb, Notes, Related articles)."""
    if not path.startswith("/press-releases/"):
        return markdown

    blocks = re.split(r"\n\s*\n", markdown.strip())
    cleaned: list[str] = []
    skip_remaining = False

    for block in blocks:
        if skip_remaining:
            continue

        lines = block.strip().split("\n")
        first = lines[0].strip()

        if re.match(r"^#+\s*$", first):
            continue

        if first.startswith("##"):
            heading = re.sub(r"^#+\s*", "", first).strip().lower()
            if heading in PRESS_RELEASE_BOILERPLATE_HEADINGS:
                if heading == "related articles":
                    skip_remaining = True
                continue

        norm = _normalize_block(block)
        if norm in PRESS_RELEASE_BOILERPLATE_HEADINGS:
            continue
        if _is_about_zearn_boilerplate(block):
            continue

        cleaned.append(block.strip())

    return "\n\n".join(cleaned)


def strip_navigational_toc(markdown: str) -> str:
    """Remove table-of-contents nav blocks if any slip through HTML cleanup."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    cleaned: list[str] = []
    for block in blocks:
        norm = _normalize_block(block)
        if norm == "table of contents":
            continue
        if norm.startswith("table of contents") and len(norm.split()) <= 12:
            continue
        cleaned.append(block.strip())
    return "\n\n".join(cleaned)


def validate_extraction(path: str, markdown: str, tab_sections_labeled: int) -> tuple[str, str | None]:
    """Return (status, error_message)."""
    word_count = len(markdown.split())
    min_words = 5 if path.startswith("/research/") else MIN_BODY_WORDS
    if word_count < min_words:
        return "static_failed", f"body too short ({word_count} words)"

    checks = TABBED_PAGE_CHECKS.get(path)
    if checks:
        missing = [kw for kw in checks if kw.lower() not in markdown.lower()]
        if missing:
            return "incomplete", f"missing expected keywords: {', '.join(missing)}"
        expected_tabs = 9 if path == "/how-zearn-math-works" else 0
        if expected_tabs and tab_sections_labeled < expected_tabs:
            return "incomplete", f"expected {expected_tabs} tab sections, labeled {tab_sections_labeled}"

    return "ok", None


def find_main_wrapper(root: BeautifulSoup | Tag) -> Tag | None:
    """Return the page content root (main or div with class main-wrapper)."""
    return root.select_one(".main-wrapper")


def find_content_between_breadcrumbs_and_footer(root: BeautifulSoup | Tag) -> Tag | None:
    """Fallback content root: siblings after breadcrumbs nav, before footer."""
    breadcrumb = root.select_one("nav.breadcrumbs_component.is-bg-white")
    footer = root.find("footer")
    if breadcrumb is None or footer is None:
        return None

    parts: list[str] = []
    el = breadcrumb.find_next_sibling()
    while el is not None and el is not footer:
        parts.append(str(el))
        el = el.find_next_sibling()

    if not parts:
        return None

    wrapper_soup = BeautifulSoup(
        f'<div class="extracted-content-root">{"".join(parts)}</div>',
        "lxml",
    )
    wrapper = wrapper_soup.select_one(".extracted-content-root")
    if wrapper is None or not wrapper.get_text(strip=True):
        return None
    return wrapper


def find_content_root(root: BeautifulSoup | Tag) -> Tag | None:
    """Return main-wrapper content, or breadcrumb-to-footer fallback."""
    return (
        find_main_wrapper(root)
        or find_content_between_breadcrumbs_and_footer(root)
        or root.select_one(".extracted-content-root")
    )


def extract_main_wrapper(html: str) -> tuple[BeautifulSoup | None, Tag | None, str | None]:
    soup = BeautifulSoup(html, "lxml")
    main = find_content_root(soup)
    if main is None:
        return soup, None, "content root not found"
    return soup, main, None


def process_page_html(
    html: str,
    url: str,
    lastmod: str | None,
    extraction_method: str = "static",
) -> tuple[str | None, dict[str, Any], str | None]:
    """Extract markdown with frontmatter from full page HTML."""
    path = url_to_path(url)
    if is_excluded_path(path):
        soup, main, err = extract_main_wrapper(html)
        meta = get_page_metadata(soup, url, lastmod) if soup else {"source_url": url}
        reason = "excluded path (espanol or blocked prefix)"
        return None, _manifest_entry(url, meta, "excluded", extraction_method, 0, 0, 0, reason), reason

    soup, main, err = extract_main_wrapper(html)
    if err or main is None:
        meta = get_page_metadata(soup, url, lastmod) if soup else {"source_url": url}
        return None, _manifest_entry(url, meta, "static_failed", extraction_method, 0, 0, 0, err), err

    main_copy = BeautifulSoup(str(main), "lxml")
    main_copy_el = find_content_root(main_copy)
    if main_copy_el is None:
        return None, {}, "failed to clone content root"

    tab_count = label_feature_tabs(main_copy_el) + label_webflow_tabs(main_copy_el)
    merge_split_headings(main_copy_el)
    prepare_main_content(main_copy_el)
    markdown_body = html_to_markdown(str(main_copy_el))
    markdown_body, deduped_removed = dedupe_markdown(markdown_body)

    path = url_to_path(url)
    markdown_body = strip_research_boilerplate(markdown_body, path)
    markdown_body = strip_press_release_boilerplate(markdown_body, path)
    markdown_body = strip_navigational_toc(markdown_body)
    markdown_body = strip_learning_acceleration_cta(markdown_body)
    markdown_body = strip_get_started_cta(markdown_body)
    markdown_body = strip_summer_math_cta_fragment(markdown_body)

    if is_mostly_spanish(markdown_body):
        meta = get_page_metadata(soup, url, lastmod)
        word_count = len(markdown_body.split())
        reason = "excluded: mostly Spanish content"
        return None, _manifest_entry(
            url, meta, "excluded", extraction_method, word_count,
            deduped_removed, tab_count, reason,
        ), reason

    meta = get_page_metadata(soup, url, lastmod)
    meta["word_count"] = len(markdown_body.split())
    meta["extraction_method"] = extraction_method

    status, validation_error = validate_extraction(path, markdown_body, tab_count)
    if status != "ok":
        return None, _manifest_entry(
            url, meta, status, extraction_method, meta["word_count"],
            deduped_removed, tab_count, validation_error,
        ), validation_error

    file_content = render_markdown_file(meta, markdown_body)
    manifest = _manifest_entry(
        url, meta, "ok", extraction_method, meta["word_count"],
        deduped_removed, tab_count, None,
    )
    return file_content, manifest, None


def _manifest_entry(
    url: str,
    meta: dict[str, Any],
    status: str,
    extraction_method: str,
    word_count: int,
    deduped_blocks_removed: int,
    tab_sections_labeled: int,
    error: str | None,
) -> dict[str, Any]:
    doc_id = meta.get("doc_id") or url_to_doc_id(url)
    return {
        "url": url,
        "filename": f"{doc_id}.md",
        "status": status,
        "extraction_method": extraction_method,
        "word_count": word_count,
        "deduped_blocks_removed": deduped_blocks_removed,
        "tab_sections_labeled": tab_sections_labeled,
        "error": error,
    }


def render_markdown_file(meta: dict[str, Any], body: str) -> str:
    frontmatter = {k: v for k, v in meta.items() if v is not None and v != ""}
    yaml_block = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_block}---\n\n{body}\n"
