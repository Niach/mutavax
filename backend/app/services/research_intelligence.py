from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


USER_AGENT = "cancerstudio-research-bot/1.0"
DEFAULT_TIMEOUT_SECONDS = 30
DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y %b %d",
    "%Y %b",
    "%Y %B %d",
    "%Y %B",
    "%b %Y",
    "%B %Y",
)


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.rstrip("/")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi or None


def parse_date_string(value: str | None) -> str | None:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        parsed = parsedate_to_datetime(raw)
        return parsed.astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass

    normalized = raw.replace("/", "-").replace("T00:00:00Z", "")
    if re.fullmatch(r"\d{4}", normalized):
        return f"{normalized}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", normalized):
        return f"{normalized}-01"
    if re.fullmatch(r"\d{4}\s+[A-Za-z]{3}", raw):
        try:
            return datetime.strptime(raw, "%Y %b").date().isoformat()
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}\s+[A-Za-z]+", raw):
        try:
            return datetime.strptime(raw, "%Y %B").date().isoformat()
        except ValueError:
            pass

    for pattern in DATE_PATTERNS:
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.date().isoformat()
        except ValueError:
            continue

    iso_candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return parsed.date().isoformat()
    except ValueError:
        return None


def parse_datetime_string(value: str | None) -> datetime | None:
    if not value:
        return None

    candidate = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def joined(values: Iterable[str], fallback: str = "none") -> str:
    flattened = [value for value in values if value]
    return ", ".join(flattened) if flattened else fallback


def trim_text(value: str | None, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


def collect_keyword_hits(item: "ResearchItem", topics: list["TopicConfig"]) -> list[str]:
    corpus = " ".join(
        [
            item.title,
            item.summary,
            str(item.metadata.get("abstract", "")),
            str(item.metadata.get("brief_summary", "")),
        ]
    ).lower()
    hits: list[str] = []
    for topic in topics:
        for keyword in topic.keywords:
            if keyword and keyword.lower() in corpus:
                hits.append(keyword)
    return unique_sorted(hits)


@dataclass
class TopicConfig:
    id: str
    title: str
    description: str
    priority: int
    paul_core: bool
    stage_tags: list[str]
    species_tags: list[str]
    keywords: list[str]
    queries: dict[str, list[str]]
    open_questions: list[str]


@dataclass
class WatchPageConfig:
    id: str
    kind: str
    title: str
    url: str
    topic_ids: list[str]
    stage_tags: list[str]
    species_tags: list[str]
    version_pattern: str | None = None
    updated_pattern: str | None = None
    title_pattern: str | None = None
    summary_template: str = ""


@dataclass
class PromotionRules:
    source_weights: dict[str, float]
    evidence_confidence: dict[str, float]
    stage_priority_boosts: dict[str, float]
    species_priority_boosts: dict[str, float]
    bucket_thresholds: dict[str, float]
    strong_preprint_threshold: float
    top_finding_count: int
    corroborated_sources_needed: int


@dataclass
class ResearchConfig:
    schema_version: int
    stage_tags: list[str]
    species_tags: list[str]
    defaults: dict[str, Any]
    topics: list[TopicConfig]
    watch_pages: list[WatchPageConfig]
    promotion_rules: PromotionRules


@dataclass
class SourceFailure:
    source_id: str
    message: str


@dataclass
class ResearchItem:
    adapter_id: str
    source_id: str
    source_type: str
    canonical_id: str
    canonical_url: str
    title: str
    published_at: str | None
    updated_at: str | None
    stage_tags: list[str]
    species_tags: list[str]
    evidence_status: str
    summary: str
    confidence: float
    novelty: float
    pipeline_impact: float
    recommended_action: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(self.confidence, 3)
        payload["novelty"] = round(self.novelty, 3)
        payload["pipeline_impact"] = round(self.pipeline_impact, 3)
        return payload


@dataclass
class ResearchFinding:
    source_type: str
    canonical_id: str
    canonical_url: str
    title: str
    published_at: str | None
    updated_at: str | None
    stage_tags: list[str]
    species_tags: list[str]
    evidence_status: str
    summary: str
    confidence: float
    novelty: float
    pipeline_impact: float
    recommended_action: str
    bucket: str
    why_it_matters: str
    next_action: str
    supporting_ids: list[str]
    topic_ids: list[str]
    score: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(self.confidence, 3)
        payload["novelty"] = round(self.novelty, 3)
        payload["pipeline_impact"] = round(self.pipeline_impact, 3)
        payload["score"] = round(self.score, 3)
        return payload


@dataclass
class ResearchRunSummary:
    run_date: str
    window_start: str
    window_end: str
    item_count: int
    finding_count: int
    source_failures: list[SourceFailure]
    brief_path: Path
    backlog_path: Path
    items_path: Path
    findings_path: Path
    dossier_paths: list[Path]


class ResearchHttpClient:
    def __init__(
        self,
        *,
        cache_root: Path | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.cache_root = cache_root
        self.timeout_seconds = timeout_seconds

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cache_key: str | None = None,
    ) -> str:
        final_url = self._build_url(url, params)
        request_headers = {"User-Agent": USER_AGENT}
        if headers:
            request_headers.update(headers)
        request = Request(final_url, headers=request_headers)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8", "replace")
        self._write_cache(cache_key or final_url, body)
        return body

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        text = self.get_text(url, params=params, headers=headers, cache_key=cache_key)
        return json.loads(text)

    def _build_url(self, url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        serialized_params = {
            key: value
            for key, value in params.items()
            if value is not None and value != ""
        }
        query = urlencode(serialized_params, doseq=True)
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{query}"

    def _write_cache(self, cache_key: str, payload: str) -> None:
        if self.cache_root is None:
            return
        digest = sha256(cache_key.encode("utf-8")).hexdigest()[:16]
        cache_path = self.cache_root / f"{digest}.txt"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(payload, encoding="utf-8")


@dataclass
class ResearchContext:
    repo_root: Path
    research_root: Path
    run_date: date
    run_started_at: datetime
    window_start: date
    window_end: date
    config: ResearchConfig
    state: dict[str, Any]
    client: ResearchHttpClient


class SourceAdapter:
    adapter_id: str

    def broad_fetch(self, context: ResearchContext) -> list[ResearchItem]:
        raise NotImplementedError

    def deepen(self, context: ResearchContext, item: ResearchItem) -> ResearchItem:
        return item


class PubMedAdapter(SourceAdapter):
    adapter_id = "pubmed"

    def broad_fetch(self, context: ResearchContext) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        retmax = int(context.config.defaults.get("maxResultsPerQuery", 3))

        for topic in context.config.topics:
            queries = topic.queries.get("pubmed", [])
            for query in queries:
                search_payload = context.client.get_json(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={
                        "db": "pubmed",
                        "term": query,
                        "retmode": "json",
                        "retmax": retmax,
                        "sort": "pub date",
                        "datetype": "pdat",
                        "mindate": context.window_start.strftime("%Y/%m/%d"),
                        "maxdate": context.window_end.strftime("%Y/%m/%d"),
                    },
                    cache_key=f"pubmed-esearch-{topic.id}-{query}",
                )
                ids = search_payload.get("esearchresult", {}).get("idlist", [])
                if not ids:
                    continue
                summary_payload = context.client.get_json(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                    params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
                    cache_key=f"pubmed-esummary-{topic.id}-{','.join(ids)}",
                )
                result_section = summary_payload.get("result", {})
                for identifier in ids:
                    entry = result_section.get(identifier)
                    if not entry:
                        continue
                    items.append(self._normalize_entry(topic, entry))
        return items

    def deepen(self, context: ResearchContext, item: ResearchItem) -> ResearchItem:
        pmid = item.metadata.get("pmid")
        if not pmid:
            return item

        xml_text = context.client.get_text(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml"},
            cache_key=f"pubmed-efetch-{pmid}",
        )
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return item

        abstract_segments = [
            trim_text(node.text, limit=500)
            for node in root.findall(".//Abstract/AbstractText")
            if node.text
        ]
        abstract = " ".join(segment for segment in abstract_segments if segment)
        if abstract:
            item.summary = trim_text(abstract, limit=500)
            item.metadata["abstract"] = abstract
            item.confidence = clamp(item.confidence + 0.04)
        return item

    def _normalize_entry(self, topic: TopicConfig, entry: dict[str, Any]) -> ResearchItem:
        doi = None
        article_ids = entry.get("articleids") or []
        for article_id in article_ids:
            if article_id.get("idtype") == "doi":
                doi = normalize_doi(article_id.get("value"))
                break

        pmid = entry.get("uid")
        authors = [author.get("name") for author in entry.get("authors", []) if author.get("name")]
        published_at = parse_date_string(entry.get("sortpubdate") or entry.get("epubdate") or entry.get("pubdate"))
        summary = (
            f"{entry.get('source', 'PubMed')} publication"
            f" focused on {topic.title.lower()}."
        )
        canonical_id = f"pmid:{pmid}"
        canonical_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if doi:
            canonical_id = f"doi:{doi}"
            canonical_url = f"https://doi.org/{doi}"

        return ResearchItem(
            adapter_id=self.adapter_id,
            source_id="pubmed",
            source_type="peer_reviewed_literature",
            canonical_id=canonical_id,
            canonical_url=canonical_url,
            title=trim_text(entry.get("title") or "Untitled PubMed record", limit=220),
            published_at=published_at,
            updated_at=published_at,
            stage_tags=list(topic.stage_tags),
            species_tags=list(topic.species_tags),
            evidence_status="peer-reviewed",
            summary=summary,
            confidence=0.0,
            novelty=0.0,
            pipeline_impact=0.0,
            recommended_action="Benchmark against current cancerstudio assumptions.",
            metadata={
                "topic_ids": [topic.id],
                "pmid": pmid,
                "doi": doi,
                "journal": entry.get("source"),
                "authors": authors[:6],
                "pubdate_raw": entry.get("pubdate"),
            },
        )


class EuropePmcAdapter(SourceAdapter):
    adapter_id = "europe_pmc"

    def broad_fetch(self, context: ResearchContext) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        page_size = int(context.config.defaults.get("maxResultsPerQuery", 3))

        for topic in context.config.topics:
            queries = topic.queries.get("europe_pmc", [])
            for query in queries:
                payload = context.client.get_json(
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    params={
                        "query": f"({query}) AND SRC:PPR",
                        "format": "json",
                        "pageSize": page_size,
                        "sort_date": "y",
                    },
                    cache_key=f"europepmc-search-{topic.id}-{query}",
                )
                results = payload.get("resultList", {}).get("result", [])
                for result in results:
                    items.append(self._normalize_entry(topic, result, context.window_start))
        return items

    def deepen(self, context: ResearchContext, item: ResearchItem) -> ResearchItem:
        preprint_id = item.metadata.get("europe_pmc_id")
        source = item.metadata.get("europe_pmc_source", "PPR")
        if not preprint_id:
            return item

        payload = context.client.get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f"EXT_ID:{preprint_id} AND SRC:{source}",
                "format": "json",
                "pageSize": 1,
                "resultType": "core",
            },
            cache_key=f"europepmc-core-{preprint_id}",
        )
        results = payload.get("resultList", {}).get("result", [])
        if not results:
            return item

        result = results[0]
        abstract = trim_text(result.get("abstractText"), limit=500)
        if abstract:
            item.summary = abstract
            item.metadata["abstract"] = abstract
        cited_by_count = result.get("citedByCount")
        if cited_by_count is not None:
            item.metadata["cited_by_count"] = cited_by_count
            item.confidence = clamp(item.confidence + min(int(cited_by_count), 5) * 0.01)
        return item

    def _normalize_entry(
        self,
        topic: TopicConfig,
        result: dict[str, Any],
        window_start: date,
    ) -> ResearchItem:
        published_at = parse_date_string(
            result.get("firstPublicationDate")
            or result.get("electronicPublicationDate")
            or result.get("pubYear")
        )
        if published_at and date.fromisoformat(published_at) < window_start:
            published_at = published_at

        doi = normalize_doi(result.get("doi"))
        europe_pmc_id = result.get("id")
        source = result.get("source") or "PPR"
        canonical_id = f"europepmc:{source}:{europe_pmc_id}"
        canonical_url = f"https://europepmc.org/article/{source}/{europe_pmc_id}"
        if doi:
            canonical_id = f"doi:{doi}"
            canonical_url = f"https://doi.org/{doi}"

        summary = trim_text(
            result.get("journalTitle")
            or f"Preprint candidate related to {topic.title.lower()}.",
            limit=220,
        )
        return ResearchItem(
            adapter_id=self.adapter_id,
            source_id="europe_pmc",
            source_type="preprint",
            canonical_id=canonical_id,
            canonical_url=canonical_url,
            title=trim_text(result.get("title") or "Untitled Europe PMC result", limit=220),
            published_at=published_at,
            updated_at=published_at,
            stage_tags=list(topic.stage_tags),
            species_tags=list(topic.species_tags),
            evidence_status="preprint",
            summary=summary,
            confidence=0.0,
            novelty=0.0,
            pipeline_impact=0.0,
            recommended_action="Monitor for corroboration or a peer-reviewed follow-up.",
            metadata={
                "topic_ids": [topic.id],
                "pmid": result.get("pmid"),
                "pmcid": result.get("pmcid"),
                "doi": doi,
                "journal": result.get("journalTitle"),
                "europe_pmc_id": europe_pmc_id,
                "europe_pmc_source": source,
            },
        )


class ClinicalTrialsAdapter(SourceAdapter):
    adapter_id = "clinical_trials"

    def broad_fetch(self, context: ResearchContext) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        page_size = int(context.config.defaults.get("maxResultsPerQuery", 3))
        version_payload = context.client.get_json(
            "https://clinicaltrials.gov/api/v2/version",
            cache_key="clinicaltrials-version",
        )
        data_timestamp = version_payload.get("dataTimestamp")
        for topic in context.config.topics:
            queries = topic.queries.get("clinical_trials", [])
            for query in queries:
                payload = context.client.get_json(
                    "https://clinicaltrials.gov/api/v2/studies",
                    params={
                        "query.term": query,
                        "pageSize": page_size,
                        "fields": (
                            "protocolSection.identificationModule,"
                            "protocolSection.statusModule,"
                            "protocolSection.descriptionModule"
                        ),
                    },
                    cache_key=f"clinicaltrials-search-{topic.id}-{query}",
                )
                studies = payload.get("studies", [])
                for study in studies:
                    item = self._normalize_entry(topic, study, data_timestamp)
                    if self._within_window(item, context.window_start):
                        items.append(item)
        return items

    def deepen(self, context: ResearchContext, item: ResearchItem) -> ResearchItem:
        nct_id = item.metadata.get("nct_id")
        if not nct_id:
            return item

        payload = context.client.get_json(
            f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
            params={
                "fields": (
                    "protocolSection.identificationModule,"
                    "protocolSection.statusModule,"
                    "protocolSection.descriptionModule"
                )
            },
            cache_key=f"clinicaltrials-detail-{nct_id}",
        )
        protocol = payload.get("protocolSection", {})
        description = protocol.get("descriptionModule", {})
        brief_summary = trim_text(description.get("briefSummary"), limit=500)
        if brief_summary:
            item.summary = brief_summary
            item.metadata["brief_summary"] = brief_summary
            item.confidence = clamp(item.confidence + 0.03)
        return item

    def _normalize_entry(
        self,
        topic: TopicConfig,
        study: dict[str, Any],
        data_timestamp: str | None,
    ) -> ResearchItem:
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        description = protocol.get("descriptionModule", {})
        nct_id = identification.get("nctId")
        updated_at = parse_date_string(
            (status.get("lastUpdatePostDateStruct") or {}).get("date")
            or status.get("statusVerifiedDate")
            or data_timestamp
        )
        published_at = parse_date_string(
            status.get("studyFirstSubmitDate")
            or (status.get("startDateStruct") or {}).get("date")
        )
        overall_status = status.get("overallStatus", "UNKNOWN")
        summary = trim_text(
            description.get("briefSummary")
            or f"{overall_status.title()} clinical activity related to {topic.title.lower()}.",
            limit=260,
        )
        title = identification.get("briefTitle") or identification.get("officialTitle") or nct_id
        return ResearchItem(
            adapter_id=self.adapter_id,
            source_id="clinical_trials",
            source_type="clinical_trial",
            canonical_id=f"nct:{nct_id}",
            canonical_url=f"https://clinicaltrials.gov/study/{nct_id}",
            title=trim_text(title or "Untitled clinical trial", limit=220),
            published_at=published_at,
            updated_at=updated_at,
            stage_tags=list(topic.stage_tags),
            species_tags=list(topic.species_tags),
            evidence_status="clinical-trial",
            summary=summary,
            confidence=0.0,
            novelty=0.0,
            pipeline_impact=0.0,
            recommended_action="Monitor recruitment, outcomes, and trial design drift.",
            metadata={
                "topic_ids": [topic.id],
                "nct_id": nct_id,
                "overall_status": overall_status,
                "brief_summary": description.get("briefSummary"),
                "data_timestamp": data_timestamp,
            },
        )

    def _within_window(self, item: ResearchItem, window_start: date) -> bool:
        updated_at = parse_date_string(item.updated_at)
        if not updated_at:
            return True
        return date.fromisoformat(updated_at) >= window_start


class WatchPageAdapter(SourceAdapter):
    adapter_id = "watch_pages"

    def broad_fetch(self, context: ResearchContext) -> list[ResearchItem]:
        items: list[ResearchItem] = []
        for page in context.config.watch_pages:
            html = context.client.get_text(
                page.url,
                cache_key=f"watch-page-{page.id}",
            )
            items.append(self._normalize_page(page, html))
        return items

    def _normalize_page(self, page: WatchPageConfig, html: str) -> ResearchItem:
        title = self._extract_pattern(html, page.title_pattern) or page.title
        version = self._extract_pattern(html, page.version_pattern)
        updated_at = parse_date_string(self._extract_pattern(html, page.updated_pattern))
        summary = page.summary_template.format(
            title=trim_text(title, limit=120),
            version=version or "current",
            updated=updated_at or "unknown",
        )
        canonical_id = page.id
        if version:
            canonical_id = f"{page.id}:{version}"

        source_type = "official_tool" if page.kind == "official_tool" else "official_resource"
        return ResearchItem(
            adapter_id=self.adapter_id,
            source_id=page.id,
            source_type=source_type,
            canonical_id=canonical_id,
            canonical_url=page.url,
            title=page.title,
            published_at=updated_at,
            updated_at=updated_at,
            stage_tags=list(page.stage_tags),
            species_tags=list(page.species_tags),
            evidence_status="official-update",
            summary=trim_text(summary, limit=260),
            confidence=0.0,
            novelty=0.0,
            pipeline_impact=0.0,
            recommended_action="Check for upstream version or reference drift against repo assumptions.",
            metadata={
                "topic_ids": list(page.topic_ids),
                "version": version,
                "observed_title": trim_text(title, limit=200),
            },
        )

    def _extract_pattern(self, html: str, pattern: str | None) -> str | None:
        if not pattern:
            return None
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        return trim_text(match.group(1), limit=120)


def load_research_config(research_root: Path) -> ResearchConfig:
    taxonomy_payload = json.loads(
        (research_root / "config" / "taxonomy.json").read_text(encoding="utf-8")
    )
    promotion_payload = json.loads(
        (research_root / "config" / "promotion_rules.json").read_text(encoding="utf-8")
    )

    topics = [
        TopicConfig(
            id=entry["id"],
            title=entry["title"],
            description=entry["description"],
            priority=int(entry["priority"]),
            paul_core=bool(entry.get("paulCore", False)),
            stage_tags=list(entry["stageTags"]),
            species_tags=list(entry["speciesTags"]),
            keywords=list(entry.get("keywords", [])),
            queries={key: list(value) for key, value in entry.get("queries", {}).items()},
            open_questions=list(entry.get("openQuestions", [])),
        )
        for entry in taxonomy_payload["topics"]
    ]
    watch_pages = [
        WatchPageConfig(
            id=entry["id"],
            kind=entry["kind"],
            title=entry["title"],
            url=entry["url"],
            topic_ids=list(entry["topicIds"]),
            stage_tags=list(entry["stageTags"]),
            species_tags=list(entry["speciesTags"]),
            version_pattern=entry.get("versionPattern"),
            updated_pattern=entry.get("updatedPattern"),
            title_pattern=entry.get("titlePattern"),
            summary_template=entry["summaryTemplate"],
        )
        for entry in taxonomy_payload.get("watchPages", [])
    ]
    promotion_rules = PromotionRules(
        source_weights=dict(promotion_payload["sourceWeights"]),
        evidence_confidence=dict(promotion_payload["evidenceConfidence"]),
        stage_priority_boosts=dict(promotion_payload["stagePriorityBoosts"]),
        species_priority_boosts=dict(promotion_payload["speciesPriorityBoosts"]),
        bucket_thresholds=dict(promotion_payload["bucketThresholds"]),
        strong_preprint_threshold=float(promotion_payload["strongPreprintThreshold"]),
        top_finding_count=int(promotion_payload["topFindingCount"]),
        corroborated_sources_needed=int(promotion_payload["corroboratedSourcesNeeded"]),
    )
    return ResearchConfig(
        schema_version=int(taxonomy_payload["schemaVersion"]),
        stage_tags=list(taxonomy_payload["stageTags"]),
        species_tags=list(taxonomy_payload["speciesTags"]),
        defaults=dict(taxonomy_payload["defaults"]),
        topics=topics,
        watch_pages=watch_pages,
        promotion_rules=promotion_rules,
    )


def build_adapters() -> list[SourceAdapter]:
    return [
        PubMedAdapter(),
        EuropePmcAdapter(),
        ClinicalTrialsAdapter(),
        WatchPageAdapter(),
    ]


def load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"seen_items": {}, "watch_versions": {}, "last_success_at": None}
    return json.loads(state_path.read_text(encoding="utf-8"))


def write_state(state_path: Path, payload: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dedupe_items(items: list[ResearchItem]) -> list[ResearchItem]:
    merged_items: list[ResearchItem] = []
    key_to_index: dict[str, int] = {}

    for item in items:
        dedupe_keys = compute_dedupe_keys(item)
        existing_index = next((key_to_index[key] for key in dedupe_keys if key in key_to_index), None)
        if existing_index is None:
            merged_items.append(item)
            item_index = len(merged_items) - 1
            for key in dedupe_keys:
                key_to_index[key] = item_index
            continue

        merged = merge_items(merged_items[existing_index], item)
        merged_items[existing_index] = merged
        for key in compute_dedupe_keys(merged):
            key_to_index[key] = existing_index

    return merged_items


def compute_dedupe_keys(item: ResearchItem) -> list[str]:
    keys = [f"id:{item.canonical_id}"]
    doi = normalize_doi(item.metadata.get("doi"))
    pmid = item.metadata.get("pmid")
    pmcid = item.metadata.get("pmcid")
    version = item.metadata.get("version")
    nct_id = item.metadata.get("nct_id")
    url = normalize_url(item.canonical_url)
    if doi:
        keys.append(f"doi:{doi}")
    if pmid:
        keys.append(f"pmid:{pmid}")
    if pmcid:
        keys.append(f"pmcid:{str(pmcid).lower()}")
    if nct_id:
        keys.append(f"nct:{nct_id}")
    if version:
        keys.append(f"version:{item.source_id}:{version}")
    if url:
        keys.append(f"url:{url}")
    return unique_sorted(keys)


def merge_items(left: ResearchItem, right: ResearchItem) -> ResearchItem:
    merged_metadata = dict(left.metadata)
    merged_metadata.update({key: value for key, value in right.metadata.items() if value not in (None, "", [], {})})
    merged_sources = unique_sorted(
        list(merged_metadata.get("seen_in_sources", [])) + [left.source_id, right.source_id]
    )
    merged_metadata["seen_in_sources"] = merged_sources
    merged_metadata["topic_ids"] = unique_sorted(
        list(left.metadata.get("topic_ids", [])) + list(right.metadata.get("topic_ids", []))
    )

    canonical_id = choose_preferred_identifier(left, right)
    canonical_url = choose_preferred_url(left, right)
    source_type = choose_preferred_source_type(left.source_type, right.source_type)
    evidence_status = choose_preferred_evidence(left.evidence_status, right.evidence_status)

    return ResearchItem(
        adapter_id=left.adapter_id,
        source_id=left.source_id,
        source_type=source_type,
        canonical_id=canonical_id,
        canonical_url=canonical_url,
        title=max([left.title, right.title], key=len),
        published_at=min([value for value in [left.published_at, right.published_at] if value], default=None),
        updated_at=max([value for value in [left.updated_at, right.updated_at] if value], default=None),
        stage_tags=unique_sorted(left.stage_tags + right.stage_tags),
        species_tags=unique_sorted(left.species_tags + right.species_tags),
        evidence_status=evidence_status,
        summary=max([left.summary, right.summary], key=len),
        confidence=max(left.confidence, right.confidence),
        novelty=max(left.novelty, right.novelty),
        pipeline_impact=max(left.pipeline_impact, right.pipeline_impact),
        recommended_action=left.recommended_action,
        metadata=merged_metadata,
    )


def choose_preferred_identifier(left: ResearchItem, right: ResearchItem) -> str:
    candidates = [left.canonical_id, right.canonical_id]
    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: (
            0 if candidate.startswith("doi:") else 1,
            -candidate.count(":"),
            -len(candidate),
        ),
    )
    return sorted_candidates[0]


def choose_preferred_url(left: ResearchItem, right: ResearchItem) -> str:
    if "doi.org" in left.canonical_url:
        return left.canonical_url
    if "doi.org" in right.canonical_url:
        return right.canonical_url
    return left.canonical_url if len(left.canonical_url) <= len(right.canonical_url) else right.canonical_url


def choose_preferred_source_type(left: str, right: str) -> str:
    priority = {
        "official_resource": 0,
        "official_tool": 1,
        "peer_reviewed_literature": 2,
        "clinical_trial": 3,
        "preprint": 4,
    }
    return left if priority.get(left, 99) <= priority.get(right, 99) else right


def choose_preferred_evidence(left: str, right: str) -> str:
    priority = {
        "official-update": 0,
        "peer-reviewed": 1,
        "clinical-trial": 2,
        "preprint": 3,
    }
    return left if priority.get(left, 99) <= priority.get(right, 99) else right


def score_items(items: list[ResearchItem], context: ResearchContext) -> list[ResearchItem]:
    topic_lookup = {topic.id: topic for topic in context.config.topics}
    rules = context.config.promotion_rules
    seen_items = context.state.get("seen_items", {})
    seen_versions = context.state.get("watch_versions", {})

    scored_items: list[ResearchItem] = []
    for item in items:
        topic_ids = item.metadata.get("topic_ids", [])
        topics = [topic_lookup[topic_id] for topic_id in topic_ids if topic_id in topic_lookup]
        topic_priority = max((topic.priority for topic in topics), default=1) / 5.0
        paul_core_bonus = 0.12 if any(topic.paul_core for topic in topics) else 0.0
        stage_boost = sum(rules.stage_priority_boosts.get(stage, 0.0) for stage in item.stage_tags)
        species_boost = sum(rules.species_priority_boosts.get(tag, 0.0) for tag in item.species_tags)
        source_weight = rules.source_weights.get(item.source_type, 0.5)
        keyword_hits = collect_keyword_hits(item, topics)
        item.metadata["keyword_hits"] = keyword_hits
        keyword_bonus = min(len(keyword_hits), 3) * 0.08
        relevance_penalty = (
            0.3
            if not keyword_hits and item.source_type in {"peer_reviewed_literature", "preprint", "clinical_trial"}
            else 0.0
        )

        seen_entry = seen_items.get(item.canonical_id)
        previous_version = seen_versions.get(item.source_id)
        item.novelty = compute_novelty(item, seen_entry, previous_version)
        base_confidence = rules.evidence_confidence.get(item.evidence_status, 0.55)
        corroboration_bonus = 0.05 * max(len(item.metadata.get("seen_in_sources", [])) - 1, 0)
        detail_bonus = 0.04 if item.metadata.get("abstract") or item.metadata.get("brief_summary") else 0.0
        confidence_penalty = 0.08 if relevance_penalty else 0.0
        item.confidence = clamp(
            max(item.confidence, base_confidence + corroboration_bonus + detail_bonus - confidence_penalty)
        )
        item.pipeline_impact = clamp(
            topic_priority
            + paul_core_bonus
            + stage_boost
            + species_boost
            + (source_weight - 0.5) * 0.25
            + keyword_bonus
            - relevance_penalty
        )
        item.recommended_action = recommend_action(item, context.config)
        scored_items.append(item)

    return sorted(
        scored_items,
        key=lambda item: (
            -(0.45 * item.confidence + 0.35 * item.pipeline_impact + 0.20 * item.novelty),
            item.canonical_id,
        ),
    )


def compute_novelty(
    item: ResearchItem,
    seen_entry: dict[str, Any] | None,
    previous_version: str | None,
) -> float:
    if seen_entry is None:
        return 1.0
    if item.metadata.get("version") and previous_version and item.metadata["version"] != previous_version:
        return 0.95
    if item.updated_at and seen_entry.get("updated_at") and item.updated_at != seen_entry["updated_at"]:
        return 0.8
    return 0.2


def recommend_action(item: ResearchItem, config: ResearchConfig) -> str:
    stages = joined(item.stage_tags)
    if item.source_type == "official_tool":
        version = item.metadata.get("version", "current")
        return f"Compare observed upstream tool docs ({version}) against repo assumptions for {stages}."
    if item.source_type == "official_resource":
        return f"Review whether resource drift changes data availability or confidence messaging for {stages}."
    if item.source_type == "clinical_trial":
        return f"Track trial movement and capture design cues that affect {stages}."
    if item.evidence_status == "preprint":
        return f"Monitor for corroboration before promoting changes to {stages}."
    return f"Benchmark this evidence against current cancerstudio defaults for {stages}."


def deepen_candidates(
    items: list[ResearchItem],
    adapters: dict[str, SourceAdapter],
    context: ResearchContext,
    top_candidates: int,
    failures: list[SourceFailure],
) -> list[ResearchItem]:
    deepened: list[ResearchItem] = []
    for index, item in enumerate(items):
        if index >= top_candidates:
            deepened.append(item)
            continue
        adapter = adapters.get(item.adapter_id)
        if adapter is None:
            deepened.append(item)
            continue
        try:
            deepened.append(adapter.deepen(context, item))
        except Exception as error:  # pragma: no cover - exercised through integration-style tests
            failures.append(SourceFailure(source_id=item.adapter_id, message=str(error)))
            deepened.append(item)
    return deepened


def build_findings(items: list[ResearchItem], context: ResearchContext) -> list[ResearchFinding]:
    topic_lookup = {topic.id: topic for topic in context.config.topics}
    rules = context.config.promotion_rules
    findings: list[ResearchFinding] = []

    for item in items:
        score = 0.45 * item.confidence + 0.35 * item.pipeline_impact + 0.20 * item.novelty
        corroborated = len(item.metadata.get("seen_in_sources", [])) >= rules.corroborated_sources_needed
        bucket = classify_bucket(item, score, corroborated, rules)
        topic_ids = list(item.metadata.get("topic_ids", []))
        topic_titles = [topic_lookup[topic_id].title for topic_id in topic_ids if topic_id in topic_lookup]
        why_it_matters = (
            f"Touches {joined(item.stage_tags)} for {joined(item.species_tags)}"
            f" and maps to {joined(topic_titles)}."
        )
        next_action = describe_next_action(item, bucket)
        findings.append(
            ResearchFinding(
                source_type=item.source_type,
                canonical_id=item.canonical_id,
                canonical_url=item.canonical_url,
                title=item.title,
                published_at=item.published_at,
                updated_at=item.updated_at,
                stage_tags=list(item.stage_tags),
                species_tags=list(item.species_tags),
                evidence_status=item.evidence_status,
                summary=item.summary,
                confidence=item.confidence,
                novelty=item.novelty,
                pipeline_impact=item.pipeline_impact,
                recommended_action=item.recommended_action,
                bucket=bucket,
                why_it_matters=why_it_matters,
                next_action=next_action,
                supporting_ids=compute_dedupe_keys(item),
                topic_ids=topic_ids,
                score=score,
            )
        )

    return sorted(findings, key=lambda finding: (-finding.score, finding.canonical_id))


def classify_bucket(
    item: ResearchItem,
    score: float,
    corroborated: bool,
    rules: PromotionRules,
) -> str:
    if item.source_type in {"peer_reviewed_literature", "preprint", "clinical_trial"} and not item.metadata.get("keyword_hits"):
        return "monitor" if score >= rules.bucket_thresholds["monitor"] else "defer"
    if item.evidence_status == "preprint" and not corroborated and score < rules.strong_preprint_threshold:
        return "monitor"
    if score >= rules.bucket_thresholds["implement"]:
        return "implement"
    if score >= rules.bucket_thresholds["benchmark"]:
        return "benchmark"
    if score >= rules.bucket_thresholds["monitor"]:
        return "monitor"
    return "defer"


def describe_next_action(item: ResearchItem, bucket: str) -> str:
    if bucket == "implement":
        return "Open an implementation issue or update the active pipeline assumptions."
    if bucket == "benchmark":
        return "Run a focused benchmark or compare the result against current defaults."
    if bucket == "monitor":
        return "Keep this on the watchlist and wait for more signal or an upstream release."
    return "Record the context only and revisit if corroborated."


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(item, sort_keys=True) for item in items]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def synthesize_outputs(
    *,
    context: ResearchContext,
    items: list[ResearchItem],
    findings: list[ResearchFinding],
    failures: list[SourceFailure],
) -> ResearchRunSummary:
    daily_root = context.research_root / "briefs" / "daily"
    brief_path = daily_root / f"{context.run_date.isoformat()}.md"
    items_path = daily_root / f"{context.run_date.isoformat()}.items.jsonl"
    findings_path = daily_root / f"{context.run_date.isoformat()}.findings.json"
    backlog_path = context.research_root / "backlog" / "pipeline-research-backlog.md"
    dossier_paths = write_dossiers(context, findings)

    top_findings = select_top_findings(
        findings,
        limit=context.config.promotion_rules.top_finding_count,
    )
    brief_body = render_daily_brief(context, items, top_findings, failures)
    brief_path.write_text(brief_body, encoding="utf-8")
    write_jsonl(items_path, [item.to_dict() for item in items])
    write_json(
        findings_path,
        {
            "runDate": context.run_date.isoformat(),
            "windowStart": context.window_start.isoformat(),
            "windowEnd": context.window_end.isoformat(),
            "findings": [finding.to_dict() for finding in findings],
        },
    )
    backlog_path.write_text(render_backlog(findings), encoding="utf-8")

    return ResearchRunSummary(
        run_date=context.run_date.isoformat(),
        window_start=context.window_start.isoformat(),
        window_end=context.window_end.isoformat(),
        item_count=len(items),
        finding_count=len(findings),
        source_failures=failures,
        brief_path=brief_path,
        backlog_path=backlog_path,
        items_path=items_path,
        findings_path=findings_path,
        dossier_paths=dossier_paths,
    )


def select_top_findings(findings: list[ResearchFinding], limit: int) -> list[ResearchFinding]:
    bucket_priority = {"implement": 0, "benchmark": 1, "monitor": 2, "defer": 3}
    official_candidates = sorted(
        [
            finding
            for finding in findings
            if finding.source_type in {"official_resource", "official_tool"}
        ],
        key=lambda finding: (
            bucket_priority.get(finding.bucket, 9),
            0 if "dog" in finding.species_tags else 1,
            len(finding.species_tags),
            -finding.score,
            finding.canonical_id,
        ),
    )
    literature_candidates = sorted(
        [
            finding
            for finding in findings
            if finding.source_type not in {"official_resource", "official_tool"}
        ],
        key=lambda finding: (
            bucket_priority.get(finding.bucket, 9),
            0 if "dog" in finding.species_tags else 1,
            -finding.score,
            finding.canonical_id,
        ),
    )

    selected: list[ResearchFinding] = []
    for candidate in official_candidates[:3] + literature_candidates[: max(limit - 3, 0)]:
        if candidate.canonical_id not in {finding.canonical_id for finding in selected}:
            selected.append(candidate)

    if len(selected) < limit:
        for candidate in findings:
            if candidate.canonical_id not in {finding.canonical_id for finding in selected}:
                selected.append(candidate)
            if len(selected) >= limit:
                break

    return selected[:limit]


def render_daily_brief(
    context: ResearchContext,
    items: list[ResearchItem],
    top_findings: list[ResearchFinding],
    failures: list[SourceFailure],
) -> str:
    lines = [
        f"# Daily Research Brief - {context.run_date.isoformat()}",
        "",
        f"- Window: {context.window_start.isoformat()} to {context.window_end.isoformat()}",
        f"- Normalized items: {len(items)}",
        f"- Promoted findings: {len(top_findings)} highlighted, {len(items)} total candidates reviewed",
        "",
        "## Top Findings",
    ]

    if not top_findings:
        lines.append("- No high-signal findings were promoted today.")
    else:
        for finding in top_findings:
            lines.append(
                f"- [{finding.title}]({finding.canonical_url})"
                f" [{finding.bucket}]"
                f" stages={joined(finding.stage_tags)}"
                f" species={joined(finding.species_tags)}"
            )
            lines.append(f"  Why it matters: {finding.why_it_matters}")
            lines.append(f"  Next action: {finding.next_action}")

    lines.extend(
        [
            "",
            "## Watch Signals",
        ]
    )
    for item in items[:8]:
        lines.append(
            f"- {item.title}: {item.summary}"
            f" (confidence {item.confidence:.2f}, impact {item.pipeline_impact:.2f})"
        )

    lines.extend(["", "## Source Failures"])
    if not failures:
        lines.append("- None.")
    else:
        for failure in failures:
            lines.append(f"- {failure.source_id}: {failure.message}")

    return "\n".join(lines) + "\n"


def render_backlog(findings: list[ResearchFinding]) -> str:
    grouped: dict[str, list[ResearchFinding]] = {
        "implement": [],
        "benchmark": [],
        "monitor": [],
        "defer": [],
    }
    for finding in findings:
        grouped[finding.bucket].append(finding)

    lines = ["# Research Backlog", ""]
    for bucket in ("implement", "benchmark", "monitor", "defer"):
        lines.append(f"## {bucket.title()}")
        entries = grouped[bucket]
        if not entries:
            lines.append("- None.")
            lines.append("")
            continue
        for finding in entries:
            lines.append(
                f"- [{finding.title}]({finding.canonical_url})"
                f" stages={joined(finding.stage_tags)}"
                f" species={joined(finding.species_tags)}"
            )
            lines.append(f"  Why: {finding.why_it_matters}")
            lines.append(f"  Next: {finding.next_action}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_dossiers(context: ResearchContext, findings: list[ResearchFinding]) -> list[Path]:
    dossier_root = context.research_root / "dossiers"
    dossier_paths: list[Path] = []
    for topic in context.config.topics:
        relevant_findings = [finding for finding in findings if topic.id in finding.topic_ids][:5]
        lines = [
            f"# {topic.title}",
            "",
            f"- Updated: {context.run_date.isoformat()}",
            f"- Stages: {joined(topic.stage_tags)}",
            f"- Species focus: {joined(topic.species_tags)}",
            f"- Priority: {topic.priority}/5",
            "",
            topic.description,
            "",
            "## Recent Findings",
        ]
        if not relevant_findings:
            lines.append("- No promoted findings yet. Keep watching the configured sources.")
        else:
            for finding in relevant_findings:
                lines.append(
                    f"- [{finding.title}]({finding.canonical_url})"
                    f" [{finding.bucket}]"
                    f" score={finding.score:.2f}"
                )
                lines.append(f"  Why: {finding.why_it_matters}")

        lines.extend(["", "## Open Questions"])
        if topic.open_questions:
            for question in topic.open_questions:
                lines.append(f"- {question}")
        else:
            lines.append("- No seeded open questions.")

        dossier_path = dossier_root / f"{slugify(topic.id)}.md"
        dossier_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        dossier_paths.append(dossier_path)
    return dossier_paths


def update_state(state: dict[str, Any], items: list[ResearchItem], run_started_at: datetime) -> dict[str, Any]:
    next_state = dict(state)
    seen_items = dict(next_state.get("seen_items", {}))
    watch_versions = dict(next_state.get("watch_versions", {}))

    for item in items:
        seen_items[item.canonical_id] = {
            "title": item.title,
            "updated_at": item.updated_at,
            "last_seen_at": run_started_at.isoformat(),
        }
        if item.metadata.get("version"):
            watch_versions[item.source_id] = item.metadata["version"]

    next_state["seen_items"] = seen_items
    next_state["watch_versions"] = watch_versions
    next_state["last_success_at"] = run_started_at.isoformat()
    return next_state


def resolve_window(
    *,
    run_date: date,
    state: dict[str, Any],
    overlap_days: int,
    initial_lookback_days: int,
) -> tuple[date, date]:
    last_success = parse_datetime_string(state.get("last_success_at"))
    if last_success is None:
        return run_date - timedelta(days=initial_lookback_days), run_date
    return last_success.date() - timedelta(days=overlap_days), run_date


def ensure_research_layout(research_root: Path) -> None:
    for relative_path in (
        "briefs/daily",
        "dossiers",
        "backlog",
        "cache",
        "state",
        "config",
    ):
        (research_root / relative_path).mkdir(parents=True, exist_ok=True)


def run_research_cycle(
    *,
    repo_root: Path,
    run_date: date | None = None,
    client: ResearchHttpClient | None = None,
    write_outputs_flag: bool = True,
) -> ResearchRunSummary:
    research_root = repo_root / "research"
    ensure_research_layout(research_root)
    config = load_research_config(research_root)
    state_path = research_root / "state" / "run-state.json"
    state = load_state(state_path)
    actual_run_date = run_date or datetime.now(timezone.utc).date()
    window_start, window_end = resolve_window(
        run_date=actual_run_date,
        state=state,
        overlap_days=int(config.defaults.get("overlapDays", 14)),
        initial_lookback_days=int(config.defaults.get("lookbackDays", 30)),
    )

    run_started_at = datetime.now(timezone.utc)
    run_slug = f"{actual_run_date.isoformat()}-{run_started_at.strftime('%H%M%S')}"
    cache_root = research_root / "cache" / run_slug if write_outputs_flag else None
    context = ResearchContext(
        repo_root=repo_root,
        research_root=research_root,
        run_date=actual_run_date,
        run_started_at=run_started_at,
        window_start=window_start,
        window_end=window_end,
        config=config,
        state=state,
        client=client or ResearchHttpClient(cache_root=cache_root),
    )

    adapters = {adapter.adapter_id: adapter for adapter in build_adapters()}
    failures: list[SourceFailure] = []
    broad_items: list[ResearchItem] = []
    for adapter in adapters.values():
        try:
            broad_items.extend(adapter.broad_fetch(context))
        except Exception as error:  # pragma: no cover - validated by degraded-source tests
            failures.append(SourceFailure(source_id=adapter.adapter_id, message=str(error)))

    deduped_items = dedupe_items(broad_items)
    scored_items = score_items(deduped_items, context)
    deepened_items = deepen_candidates(
        scored_items,
        adapters,
        context,
        top_candidates=int(config.defaults.get("topCandidatesToDeepen", 8)),
        failures=failures,
    )
    rescored_items = score_items(deepened_items, context)
    findings = build_findings(rescored_items, context)

    summary = synthesize_outputs(
        context=context,
        items=rescored_items,
        findings=findings,
        failures=failures,
    )
    if write_outputs_flag:
        write_state(state_path, update_state(state, rescored_items, run_started_at))
    return summary
