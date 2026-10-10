import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse


_DOMAIN_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_REL_SPLIT_RE = re.compile(r"[\s/]+")
_CSS_URL_RE = re.compile(
    r"""url\(\s*(?P<quote>["']?)(?P<url>[^"')]+)(?P=quote)\s*\)""",
    re.IGNORECASE,
)

_SKIP_SCHEMES = (
    "data:",
    "blob:",
    "javascript:",
    "mailto:",
    "tel:",
    "about:",
    "file:",
)

_EXTENSION_TYPES = {
    "js": "js",
    "mjs": "js",
    "css": "css",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "svg": "image",
    "avif": "image",
    "ico": "image",
    "woff": "font",
    "woff2": "font",
    "ttf": "font",
    "otf": "font",
    "eot": "font",
    "mp4": "media",
    "webm": "media",
    "ogg": "media",
    "mp3": "media",
    "wav": "media",
    "html": "html",
    "php": "html",
    "asp": "html",
    "aspx": "html",
}

_CRITICAL_ASSET_TYPES = {"js", "css", "image", "font"}
_CRITICAL_TYPE_PRIORITY = {
    "js": 0,
    "css": 1,
    "image": 2,
    "font": 3,
}


@dataclass
class ExtractedAsset:
    raw_url: str
    absolute_url: Optional[str]
    domain: Optional[str]
    path: Optional[str]
    asset_type: str
    source: str
    is_external: bool
    is_relative: bool
    integrity: Optional[str] = None
    crossorigin: Optional[str] = None
    confidence: str = "medium"


@dataclass
class AuxiliaryDomainCandidate:
    domain: str
    source: str
    confidence: str
    reason: str
    sample_urls: List[str] = field(default_factory=list)
    asset_types: List[str] = field(default_factory=list)
    count: int = 1


@dataclass
class AssetExtractionResult:
    base_domain: str
    base_url: Optional[str]
    page_url: Optional[str]
    assets: List[ExtractedAsset] = field(default_factory=list)
    auxiliary_candidates: List[AuxiliaryDomainCandidate] = field(default_factory=list)
    critical_assets: List[ExtractedAsset] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _normalize_domain(domain: Any) -> str:
    try:
        return str(domain).strip().lower().rstrip(".")
    except Exception:
        return ""


def _is_valid_domain(domain: str) -> bool:
    if not domain:
        return False
    if not _DOMAIN_RE.fullmatch(domain):
        return False
    if domain == "localhost":
        return True
    return "." in domain


def _has_scheme(raw: str) -> bool:
    return bool(_SCHEME_RE.match(raw or ""))


def _skip_reason(raw: str) -> Optional[str]:
    if not raw:
        return "empty"
    if raw.startswith("#"):
        return "fragment"
    low = raw.lower()
    for scheme in _SKIP_SCHEMES:
        if low.startswith(scheme):
            return "non_http"
    return None


def _is_ip_like(domain: str) -> bool:
    if not domain:
        return False
    if ":" in domain:
        return True
    parts = domain.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or len(part) > 3:
            return False
        try:
            if int(part) > 255:
                return False
        except Exception:
            return False
    return True


def _primary_label(domain: str) -> str:
    labels = [label for label in (domain or "").split(".") if label]
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return labels[-2]


def _classify_by_path(path: Optional[str]) -> str:
    if not path:
        return "other"
    lowered = path.lower()
    basename = lowered.rsplit("/", 1)[-1]
    if "." not in basename:
        return "other"
    ext = basename.rsplit(".", 1)[-1]
    return _EXTENSION_TYPES.get(ext, "other")


class _BaseHrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: List[Optional[str]] = []
        self.parse_error: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        try:
            if tag == "base" and len(self.hrefs) < 10:
                for key, value in attrs:
                    if key.lower() == "href":
                        self.hrefs.append(value)
                        break
        except Exception as exc:
            self.parse_error = str(exc)


class _AssetParser(HTMLParser):
    def __init__(self, tag_handler, css_handler) -> None:
        super().__init__(convert_charrefs=True)
        self.tag_handler = tag_handler
        self.css_handler = css_handler
        self.in_style = False
        self.style_chunks: List[str] = []
        self.parse_error: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        try:
            attrd: Dict[str, Optional[str]] = {}
            for key, value in attrs:
                attrd[key.lower()] = value

            if tag == "style":
                self.in_style = True
                self.style_chunks = []

            self.tag_handler(tag, attrd)
        except Exception as exc:
            self.parse_error = str(exc)

    def handle_data(self, data: str) -> None:
        try:
            if self.in_style and data:
                self.style_chunks.append(data)
        except Exception as exc:
            self.parse_error = str(exc)

    def handle_endtag(self, tag: str) -> None:
        try:
            if tag == "style" and self.in_style:
                css = "".join(self.style_chunks)
                self.in_style = False
                self.style_chunks = []
                self.css_handler(css, "style_tag")
        except Exception as exc:
            self.parse_error = str(exc)

    def close(self) -> None:
        try:
            if self.in_style:
                css = "".join(self.style_chunks)
                self.in_style = False
                self.style_chunks = []
                self.css_handler(css, "style_tag")
        except Exception as exc:
            self.parse_error = str(exc)
        finally:
            super().close()


def extract_assets_from_html(
    html: str,
    base_domain: str,
    *,
    base_url: Optional[str] = None,
    page_url: Optional[str] = None,
    max_critical_assets: int = 8,
) -> AssetExtractionResult:
    errors: List[str] = []
    warnings: List[str] = []
    warning_set = set()
    unresolved_set = set()

    assets: List[ExtractedAsset] = []
    candidates: List[AuxiliaryDomainCandidate] = []
    critical: List[ExtractedAsset] = []

    bd = ""
    effective_base_url: Optional[str] = None
    page_out: Optional[str] = None

    def add_warning(message: str) -> None:
        if not message:
            return
        if message in warning_set:
            return
        if len(warnings) >= 50:
            return
        warnings.append(message)
        warning_set.add(message)

    def add_unresolved(raw: str) -> None:
        if len(unresolved_set) >= 20:
            return
        if raw in unresolved_set:
            return
        unresolved_set.add(raw)
        add_warning(f"unresolved_url:{raw}")

    try:
        bd = _normalize_domain(base_domain)
        if not _is_valid_domain(bd):
            return AssetExtractionResult(
                base_domain="",
                base_url=None,
                page_url=None,
                assets=assets,
                auxiliary_candidates=candidates,
                critical_assets=critical,
                errors=["invalid_base_domain"],
                warnings=warnings,
            )

        if html is None:
            fallback_base = f"https://{bd}/"
            return AssetExtractionResult(
                base_domain=bd,
                base_url=fallback_base,
                page_url=fallback_base,
                assets=assets,
                auxiliary_candidates=candidates,
                critical_assets=critical,
                errors=["invalid_html"],
                warnings=warnings,
            )

        if isinstance(html, (bytes, bytearray)):
            try:
                html_text = bytes(html).decode("utf-8", errors="replace")
            except Exception:
                fallback_base = f"https://{bd}/"
                return AssetExtractionResult(
                    base_domain=bd,
                    base_url=fallback_base,
                    page_url=fallback_base,
                    assets=assets,
                    auxiliary_candidates=candidates,
                    critical_assets=critical,
                    errors=["invalid_html"],
                    warnings=warnings,
                )
        else:
            try:
                html_text = str(html)
            except Exception:
                fallback_base = f"https://{bd}/"
                return AssetExtractionResult(
                    base_domain=bd,
                    base_url=fallback_base,
                    page_url=fallback_base,
                    assets=assets,
                    auxiliary_candidates=candidates,
                    critical_assets=critical,
                    errors=["invalid_html"],
                    warnings=warnings,
                )

        if base_url is None:
            original_base_url = f"https://{bd}/"
        else:
            try:
                original_base_url = str(base_url).strip()
            except Exception:
                original_base_url = ""
            if not original_base_url:
                original_base_url = f"https://{bd}/"

        parsed_base = urlparse(original_base_url)
        if parsed_base.scheme not in ("http", "https") and not original_base_url.startswith("//"):
            if original_base_url.startswith("/"):
                original_base_url = f"https://{bd}{original_base_url}"
            else:
                original_base_url = f"https://{original_base_url}"

        if page_url is None:
            page_out = original_base_url
        else:
            try:
                page_out = str(page_url).strip() or original_base_url
            except Exception:
                page_out = original_base_url

        effective_base_url = original_base_url

        try:
            base_parser = _BaseHrefParser()
            base_parser.feed(html_text)
            base_parser.close()

            if base_parser.hrefs:
                found_valid_base = False
                for href in base_parser.hrefs:
                    try:
                        href_str = str(href).strip() if href is not None else ""
                    except Exception:
                        href_str = ""
                    if not href_str:
                        continue
                    try:
                        joined = urljoin(original_base_url, href_str)
                        parsed_join = urlparse(joined)
                        if parsed_join.scheme in ("http", "https"):
                            effective_base_url = joined
                            found_valid_base = True
                            break
                    except Exception:
                        continue
                if not found_valid_base:
                    add_warning("invalid_base_href")
        except Exception:
            add_warning("invalid_base_href")

        skipped_non_http = 0
        skipped_ip = False
        parse_errors: List[str] = []

        def add_asset(
            raw: Any,
            source: str,
            forced_type: Optional[str] = None,
            integrity: Optional[str] = None,
            crossorigin: Optional[str] = None,
        ) -> None:
            nonlocal skipped_non_http

            try:
                raw_str = str(raw).strip() if raw is not None else ""
            except Exception:
                return

            if not raw_str:
                return

            reason = _skip_reason(raw_str)
            if reason in ("empty", "fragment"):
                return
            if reason == "non_http":
                skipped_non_http += 1
                return

            try:
                absolute = urljoin(effective_base_url or original_base_url, raw_str)
                parsed = urlparse(absolute)
                scheme = (parsed.scheme or "").lower()
                if scheme not in ("http", "https"):
                    skipped_non_http += 1
                    return
                domain = _normalize_domain(parsed.hostname) if parsed.hostname else None
                path = parsed.path or None
            except Exception:
                add_unresolved(raw_str)
                return

            asset_type = forced_type or _classify_by_path(path)
            if not asset_type:
                asset_type = "other"

            is_external = bool(domain and domain != bd)
            is_relative = not _has_scheme(raw_str) and not raw_str.startswith("//")

            if asset_type in _CRITICAL_ASSET_TYPES:
                confidence = "high"
            elif asset_type == "link":
                confidence = "low"
            else:
                confidence = "medium"

            assets.append(
                ExtractedAsset(
                    raw_url=raw_str,
                    absolute_url=absolute,
                    domain=domain,
                    path=path,
                    asset_type=asset_type,
                    source=source,
                    is_external=is_external,
                    is_relative=is_relative,
                    integrity=str(integrity) if integrity else None,
                    crossorigin=str(crossorigin) if crossorigin else None,
                    confidence=confidence,
                )
            )

        def process_css(css_text: str, source: str) -> None:
            if not css_text:
                return
            try:
                matches = _CSS_URL_RE.findall(css_text)
            except Exception:
                return

            for _quote, url_value in matches:
                add_asset(url_value, source)

        def handle_tag(tag: str, attrd: Dict[str, Optional[str]]) -> None:
            try:
                if tag == "script":
                    for attr in ("src", "data-src"):
                        value = attrd.get(attr)
                        if value:
                            add_asset(
                                value,
                                f"script.{attr}",
                                "js",
                                integrity=attrd.get("integrity"),
                                crossorigin=attrd.get("crossorigin"),
                            )

                elif tag == "link":
                    href = attrd.get("href")
                    if href:
                        rel = (attrd.get("rel") or "").lower()
                        as_value = (attrd.get("as") or "").lower()
                        tokens = {token for token in _REL_SPLIT_RE.split(rel) if token}

                        forced_type: Optional[str] = None
                        if "stylesheet" in tokens:
                            forced_type = "css"
                        elif "icon" in tokens or "apple-touch-icon" in tokens:
                            forced_type = "icon"
                        elif "preload" in tokens:
                            if as_value == "style":
                                forced_type = "css"
                            elif as_value == "script":
                                forced_type = "js"
                            elif as_value == "font":
                                forced_type = "font"
                            elif as_value == "image":
                                forced_type = "image"

                        add_asset(
                            href,
                            "link.href",
                            forced_type,
                            integrity=attrd.get("integrity"),
                            crossorigin=attrd.get("crossorigin"),
                        )

                elif tag == "img":
                    for attr in ("src", "data-src", "poster"):
                        value = attrd.get(attr)
                        if value:
                            add_asset(value, f"img.{attr}", "image")

                elif tag == "iframe":
                    value = attrd.get("src")
                    if value:
                        add_asset(value, "iframe.src", "embed")

                elif tag == "embed":
                    value = attrd.get("src")
                    if value:
                        add_asset(value, "embed.src", "embed")

                elif tag == "source":
                    value = attrd.get("src")
                    if value:
                        add_asset(value, "source.src", "media")

                elif tag == "video":
                    for attr in ("src", "poster"):
                        value = attrd.get(attr)
                        if value:
                            add_asset(value, f"video.{attr}", "media")

                elif tag == "audio":
                    value = attrd.get("src")
                    if value:
                        add_asset(value, "audio.src", "media")

                elif tag == "object":
                    value = attrd.get("data")
                    if value:
                        add_asset(value, "object.data", "embed")

                elif tag == "a":
                    value = attrd.get("href")
                    if value:
                        add_asset(value, "a.href", "link")

                style_attr = attrd.get("style")
                if style_attr:
                    process_css(style_attr, "style_attr")

            except Exception as exc:
                parse_errors.append(str(exc))

        try:
            parser = _AssetParser(handle_tag, process_css)
            parser.feed(html_text)
            parser.close()

            if getattr(parser, "parse_error", None):
                parse_errors.append(parser.parse_error)
        except Exception as exc:
            parse_errors.append(str(exc))

        if parse_errors:
            message = f"html_parse_exception:{parse_errors[0]}"
            if not any(err.startswith("html_parse_exception:") for err in errors):
                errors.append(message)

        if skipped_non_http > 0:
            add_warning("skipped_non_http_urls")

        if not assets:
            add_warning("no_assets")

        accum: Dict[str, Dict[str, Any]] = {}

        for asset in assets:
            dom = asset.domain
            if not dom or dom == bd:
                continue

            if _is_ip_like(dom):
                skipped_ip = True
                continue

            acc = accum.get(dom)
            if acc is None:
                acc = {
                    "count": 0,
                    "samples": [],
                    "sample_set": set(),
                    "types": [],
                    "type_set": set(),
                    "source_rank": 3,
                    "has_critical": False,
                    "has_non_link_asset": False,
                }
                accum[dom] = acc

            acc["count"] += 1

            abs_url = asset.absolute_url
            if abs_url and abs_url not in acc["sample_set"] and len(acc["samples"]) < 3:
                acc["samples"].append(abs_url)
                acc["sample_set"].add(abs_url)

            asset_type = asset.asset_type
            if asset_type and asset_type not in acc["type_set"] and len(acc["types"]) < 5:
                acc["types"].append(asset_type)
                acc["type_set"].add(asset_type)

            if asset_type in _CRITICAL_ASSET_TYPES:
                acc["has_critical"] = True

            if asset.source != "a.href" and asset_type != "link":
                acc["has_non_link_asset"] = True

            if asset.source in ("style_attr", "style_tag"):
                rank = 1
            elif asset.source == "a.href" or asset_type == "link":
                rank = 2
            else:
                rank = 0

            if rank < acc["source_rank"]:
                acc["source_rank"] = rank

        if skipped_ip:
            add_warning("skipped_ip_asset_domain")

        primary = _primary_label(bd)

        for dom, acc in accum.items():
            if acc["has_critical"]:
                confidence = "high"
                reason = "hosts critical page assets"
            elif acc["has_non_link_asset"]:
                confidence = "medium"
                reason = "hosts page assets"
            else:
                confidence = "low"
                reason = "only linked from page"

            rank = int(acc["source_rank"])
            if rank == 0:
                source = "html_asset"
            elif rank == 1:
                source = "style_url"
            else:
                source = "html_link"

            if primary and primary in dom.split(".") and acc["has_non_link_asset"]:
                confidence = "high"
                reason = "domain shares brand label with base domain"

            candidates.append(
                AuxiliaryDomainCandidate(
                    domain=dom,
                    source=source,
                    confidence=confidence,
                    reason=reason,
                    sample_urls=list(acc["samples"]),
                    asset_types=list(acc["types"]),
                    count=int(acc["count"]),
                )
            )

        confidence_order = {"high": 0, "medium": 1, "low": 2}
        candidates.sort(
            key=lambda item: (
                confidence_order.get(item.confidence, 3),
                -item.count,
                item.domain,
            )
        )

        try:
            max_int = int(max_critical_assets)
        except Exception:
            max_int = 8

        if max_int <= 0:
            add_warning("critical_assets_disabled")
            critical = []
        else:
            seen_critical_urls = set()
            ranked_critical = []

            for idx, asset in enumerate(assets):
                if (
                    asset.absolute_url
                    and asset.asset_type in _CRITICAL_ASSET_TYPES
                    and asset.absolute_url not in seen_critical_urls
                ):
                    seen_critical_urls.add(asset.absolute_url)
                    priority = _CRITICAL_TYPE_PRIORITY.get(asset.asset_type, 99)
                    ranked_critical.append((priority, idx, asset))

            ranked_critical.sort(key=lambda item: (item[0], item[1]))

            if len(ranked_critical) > max_int:
                add_warning("critical_assets_truncated")

            critical = [item[2] for item in ranked_critical[:max_int]]

        return AssetExtractionResult(
            base_domain=bd,
            base_url=effective_base_url,
            page_url=page_out,
            assets=assets,
            auxiliary_candidates=candidates,
            critical_assets=critical,
            errors=errors,
            warnings=warnings,
        )

    except Exception as exc:
        message = f"html_parse_exception:{exc}"
        if not any(err.startswith("html_parse_exception:") for err in errors):
            errors.append(message)

        return AssetExtractionResult(
            base_domain=bd,
            base_url=effective_base_url,
            page_url=page_out,
            assets=assets,
            auxiliary_candidates=candidates,
            critical_assets=critical,
            errors=errors,
            warnings=warnings,
        )
