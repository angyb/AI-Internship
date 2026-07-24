"""Shared HTML → markdown extraction for help.zearn.org Zendesk articles."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import html2text
import yaml
from bs4 import BeautifulSoup, Tag

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MIN_BODY_WORDS = 20
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

STANDALONE_CTA_LINES = {
    "text link",
    "learn more",
    "read more",
    "contact us",
    "sign up",
    "log in",
    "get started",
}

STRIP_LINE_PREFIXES = (
    "click here",
    "learn more",
    "download and print",
)

ARTICLE_DOC_ID_OVERRIDES = {
    38664432460951: "merging-existing-accounts-clever",
    38664687543575: "merging-existing-accounts-classlink",
    236174908: "omitted-digital-lessons",
}

EXCLUDED_ARTICLE_IDS = frozenset({5253628244759, 360052425773})

SPANISH_TITLE_SUFFIX = re.compile(r"\(Spanish\)\s*$", re.I)


def is_spanish_language_article(article: dict[str, Any]) -> bool:
    """English help-center articles whose body is in Spanish (title ends with '(Spanish)')."""
    return bool(SPANISH_TITLE_SUFFIX.search(article.get("title") or ""))


def is_excluded_article(article: dict[str, Any]) -> bool:
    return article.get("id") in EXCLUDED_ARTICLE_IDS or is_spanish_language_article(article)


def url_to_doc_id(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = path.split("/")[-1] if path else "index"
    slug = re.sub(r"^\d+-", "", slug)
    return slug.lower()


def assign_doc_ids(articles: list[dict[str, Any]]) -> dict[int, str]:
    """Return unique doc_id per article; suffix article_id only when slugs collide."""
    eligible = [article for article in articles if not is_excluded_article(article)]
    base_ids = [url_to_doc_id(article["html_url"]) for article in eligible]
    counts: dict[str, int] = {}
    for doc_id in base_ids:
        counts[doc_id] = counts.get(doc_id, 0) + 1

    assigned: dict[int, str] = {}
    for article in articles:
        article_id = article["id"]
        if is_excluded_article(article):
            continue
        if article_id in ARTICLE_DOC_ID_OVERRIDES:
            assigned[article_id] = ARTICLE_DOC_ID_OVERRIDES[article_id]
            continue
        base = url_to_doc_id(article["html_url"])
        if counts[base] > 1:
            assigned[article_id] = f"{base}-{article_id}"
        else:
            assigned[article_id] = base
    return assigned


def clean_title(raw: str) -> str:
    title = re.sub(r"\s+", " ", raw).strip()
    for sep in (" | ", " - ", " — "):
        if sep in title:
            title = title.split(sep)[0].strip()
            break
    return title


def extract_article_html(full_page_html: str) -> Tag | None:
    soup = BeautifulSoup(full_page_html, "lxml")
    return soup.find("article")


def extract_article_title(article: Tag) -> str | None:
    header = article.find("header")
    if header is not None:
        h1 = header.find("h1")
        if h1 is not None:
            return clean_title(h1.get_text(" ", strip=True))
    h1 = article.find("h1")
    if h1 is not None:
        return clean_title(h1.get_text(" ", strip=True))
    return None


def prepare_article_content(root: Tag) -> None:
    """Remove chrome and normalize article HTML before markdown conversion."""
    for selector in (
        'div.my-6[data-element="article-navigation"]',
        "footer",
        '[data-element="article-navigation"]',
        ".article-votes",
        ".article-subscribe",
        ".article-return-to-top",
    ):
        for el in root.select(selector):
            el.decompose()

    for br in root.find_all("br"):
        br.replace_with(" ")

    for anchor in root.find_all("a"):
        if _is_inline_link(anchor):
            anchor.replace_with(anchor.get_text(" ", strip=True))
        else:
            anchor.decompose()

    for tag in root.find_all(["strong", "b", "em", "i"]):
        tag.unwrap()

    for tag in root.find_all(["script", "style", "iframe", "video", "svg", "picture", "source"]):
        tag.decompose()

    for img in root.find_all("img"):
        img.decompose()


def _is_inline_link(anchor: Tag) -> bool:
    parent = anchor.parent
    if parent is None:
        return False
    if parent.name in ("p", "li", "span", "em", "i", *HEADING_TAGS):
        return True
    if parent.name in ("div", "section", "article", "td", "th", "header"):
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


def _should_strip_line(stripped: str) -> bool:
    norm = re.sub(r"\s+", " ", stripped).lower()
    if norm in STANDALONE_CTA_LINES:
        return True
    return any(norm.startswith(prefix) for prefix in STRIP_LINE_PREFIXES)


def clean_markdown(md: str) -> str:
    md = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    md = re.sub(r"__(.+?)__", r"\1", md)
    md = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\[\s*\]", "", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    lines = []
    for line in md.splitlines():
        stripped = line.strip()
        if re.match(r"^#+\s*$", stripped):
            continue
        if _should_strip_line(stripped):
            continue
        lines.append(line.rstrip())
    md = "\n".join(lines)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = normalize_list_indentation(md)
    md = re.sub(r"^(#+)\s+", r"\1 ", md, flags=re.M)
    return md.rstrip()


def process_article_page_html(full_page_html: str) -> tuple[str | None, str | None, str | None]:
    """Extract markdown and title from a full help center article page."""
    article = extract_article_html(full_page_html)
    if article is None:
        return None, None, "article tag not found"

    title = extract_article_title(article)
    prepare_article_content(article)
    markdown_body = html_to_markdown(str(article))
    if len(markdown_body.split()) < MIN_BODY_WORDS:
        return None, title, f"body too short ({len(markdown_body.split())} words)"
    return markdown_body, title, None


def build_metadata(
    article: dict[str, Any],
    section_name: str | None,
    category_name: str | None,
    extraction_method: str,
    page_title: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    html_url = article["html_url"]
    scraped_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    title = page_title or clean_title(article.get("title") or article.get("name") or "")
    return {
        "doc_id": doc_id or url_to_doc_id(html_url),
        "source_url": html_url,
        "title": title,
        "source_site": urlparse(html_url).netloc,
        "source_type": "zendesk",
        "language": "en",
        "article_id": article.get("id"),
        "section": (section_name or "").strip(),
        "category": (category_name or "").strip(),
        "updated_at": article.get("updated_at"),
        "scraped_at": scraped_at,
        "extraction_method": extraction_method,
    }


def process_article_page(
    article: dict[str, Any],
    full_page_html: str,
    section_name: str | None,
    category_name: str | None,
    extraction_method: str = "playwright",
    doc_id: str | None = None,
) -> tuple[str | None, dict[str, Any], str | None]:
    markdown_body, page_title, error = process_article_page_html(full_page_html)
    meta = build_metadata(
        article, section_name, category_name, extraction_method, page_title=page_title, doc_id=doc_id
    )
    word_count = len(markdown_body.split()) if markdown_body else 0
    meta["word_count"] = word_count

    if error or markdown_body is None:
        return None, _manifest_entry(
            article["html_url"], meta, "static_failed", extraction_method, word_count, error=error
        ), error

    file_content = render_markdown_file(meta, markdown_body)
    manifest = _manifest_entry(
        article["html_url"], meta, "ok", extraction_method, word_count, error=None
    )
    return file_content, manifest, None


def render_markdown_file(meta: dict[str, Any], body: str) -> str:
    frontmatter = {k: v for k, v in meta.items() if v is not None and v != ""}
    yaml_block = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{yaml_block}---\n\n{body}\n"


def _manifest_entry(
    url: str,
    meta: dict[str, Any],
    status: str,
    extraction_method: str,
    word_count: int,
    error: str | None,
) -> dict[str, Any]:
    doc_id = meta.get("doc_id") or url_to_doc_id(url)
    return {
        "url": url,
        "filename": f"{doc_id}.md",
        "status": status,
        "extraction_method": extraction_method,
        "word_count": word_count,
        "error": error,
    }
