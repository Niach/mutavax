import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.services import research_intelligence as research


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "research"


class FixtureClient:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def get_text(self, url, *, params=None, headers=None, cache_key=None):
        key = cache_key or url
        for prefix, payload in self.mapping.items():
            if key.startswith(prefix):
                return payload
        raise AssertionError(f"Unexpected fixture request: {key}")

    def get_json(self, url, *, params=None, headers=None, cache_key=None):
        return json.loads(self.get_text(url, params=params, headers=headers, cache_key=cache_key))


def read_fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def make_rules() -> research.PromotionRules:
    return research.PromotionRules(
        source_weights={
            "peer_reviewed_literature": 0.76,
            "preprint": 0.5,
            "clinical_trial": 0.68,
            "official_resource": 0.82,
            "official_tool": 0.79,
        },
        evidence_confidence={
            "peer-reviewed": 0.84,
            "preprint": 0.52,
            "clinical-trial": 0.72,
            "official-update": 0.81,
        },
        stage_priority_boosts={
            "variant-calling": 0.12,
            "annotation": 0.1,
            "neoantigen-prediction": 0.18,
            "epitope-selection": 0.14,
            "construct-design": 0.1,
            "construct-output": 0.08,
        },
        species_priority_boosts={
            "human": 0.06,
            "dog": 0.12,
            "cat": 0.04,
            "cross-species": 0.05,
        },
        bucket_thresholds={"implement": 0.82, "benchmark": 0.67, "monitor": 0.45},
        strong_preprint_threshold=0.9,
        top_finding_count=5,
        corroborated_sources_needed=2,
    )


def make_topic(
    *,
    topic_id: str,
    title: str,
    stage_tags: list[str],
    species_tags: list[str],
    queries: dict[str, list[str]],
    priority: int = 5,
    paul_core: bool = True,
) -> research.TopicConfig:
    return research.TopicConfig(
        id=topic_id,
        title=title,
        description=f"Tracks {title.lower()} evidence.",
        priority=priority,
        paul_core=paul_core,
        stage_tags=stage_tags,
        species_tags=species_tags,
        keywords=[],
        queries=queries,
        open_questions=["What should change next?"],
    )


def make_config(
    *,
    topics: list[research.TopicConfig],
    watch_pages: list[research.WatchPageConfig] | None = None,
) -> research.ResearchConfig:
    return research.ResearchConfig(
        schema_version=1,
        stage_tags=[
            "ingestion",
            "alignment",
            "variant-calling",
            "annotation",
            "neoantigen-prediction",
            "epitope-selection",
            "construct-design",
            "structure-prediction",
            "construct-output",
            "ai-review",
        ],
        species_tags=["human", "dog", "cat", "cross-species"],
        defaults={
            "lookbackDays": 30,
            "overlapDays": 14,
            "maxResultsPerQuery": 3,
            "topCandidatesToDeepen": 8,
        },
        topics=topics,
        watch_pages=watch_pages or [],
        promotion_rules=make_rules(),
    )


def make_context(
    tmp_path: Path,
    *,
    config: research.ResearchConfig,
    client,
    state: dict | None = None,
) -> research.ResearchContext:
    research_root = tmp_path / "research"
    research.ensure_research_layout(research_root)
    return research.ResearchContext(
        repo_root=tmp_path,
        research_root=research_root,
        run_date=date(2026, 4, 12),
        run_started_at=datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc),
        window_start=date(2026, 3, 29),
        window_end=date(2026, 4, 12),
        config=config,
        state=state or {"seen_items": {}, "watch_versions": {}, "last_success_at": None},
        client=client,
    )


def make_item(
    *,
    canonical_id: str,
    canonical_url: str,
    source_type: str,
    evidence_status: str,
    title: str = "Signal",
    stage_tags: list[str] | None = None,
    species_tags: list[str] | None = None,
    metadata: dict | None = None,
) -> research.ResearchItem:
    return research.ResearchItem(
        adapter_id="test",
        source_id="test",
        source_type=source_type,
        canonical_id=canonical_id,
        canonical_url=canonical_url,
        title=title,
        published_at="2026-04-10",
        updated_at="2026-04-10",
        stage_tags=stage_tags or ["neoantigen-prediction"],
        species_tags=species_tags or ["dog"],
        evidence_status=evidence_status,
        summary="Useful signal for cancerstudio.",
        confidence=0.8,
        novelty=0.8,
        pipeline_impact=0.8,
        recommended_action="Act on it.",
        metadata=metadata or {"topic_ids": ["neoantigen-prediction"]},
    )


def test_pubmed_adapter_normalizes_and_deepens_peer_reviewed_item(tmp_path: Path):
    client = FixtureClient(
        {
            "pubmed-esearch": read_fixture("pubmed_esearch.json"),
            "pubmed-esummary": read_fixture("pubmed_esummary.json"),
            "pubmed-efetch": read_fixture("pubmed_efetch.xml"),
        }
    )
    config = make_config(
        topics=[
            make_topic(
                topic_id="neoantigen-prediction",
                title="Neoantigen prediction",
                stage_tags=["neoantigen-prediction"],
                species_tags=["dog", "cross-species"],
                queries={"pubmed": ["personalized neoantigen prediction cancer vaccine"]},
            )
        ]
    )
    context = make_context(tmp_path, config=config, client=client)

    adapter = research.PubMedAdapter()
    items = adapter.broad_fetch(context)

    assert len(items) == 1
    item = items[0]
    assert item.canonical_id == "doi:10.1002/advs.202501234"
    assert item.stage_tags == ["neoantigen-prediction"]
    assert item.species_tags == ["dog", "cross-species"]

    deepened = adapter.deepen(context, item)
    assert "co-administered" in deepened.summary.lower()


def test_europe_pmc_adapter_marks_preprint_and_deepens_abstract(tmp_path: Path):
    client = FixtureClient(
        {
            "europepmc-search": read_fixture("europepmc_search.json"),
            "europepmc-core": read_fixture("europepmc_core.json"),
        }
    )
    config = make_config(
        topics=[
            make_topic(
                topic_id="mhc-dla-resources",
                title="MHC and DLA resources",
                stage_tags=["neoantigen-prediction", "epitope-selection"],
                species_tags=["dog", "cross-species"],
                queries={"europe_pmc": ["canine immunopeptidome DLA"]},
            )
        ]
    )
    context = make_context(tmp_path, config=config, client=client)

    adapter = research.EuropePmcAdapter()
    items = adapter.broad_fetch(context)

    assert len(items) == 1
    item = items[0]
    assert item.evidence_status == "preprint"
    assert item.canonical_id == "doi:10.1101/2026.04.01.123456"

    deepened = adapter.deepen(context, item)
    assert "immunopeptidomics" in deepened.summary.lower()
    assert deepened.metadata["cited_by_count"] == 2


def test_clinical_trials_adapter_normalizes_and_deepens_study(tmp_path: Path):
    client = FixtureClient(
        {
            "clinicaltrials-version": read_fixture("clinical_trials_version.json"),
            "clinicaltrials-search": read_fixture("clinical_trials_search.json"),
            "clinicaltrials-detail": read_fixture("clinical_trials_detail.json"),
        }
    )
    config = make_config(
        topics=[
            make_topic(
                topic_id="regulatory-and-clinical-signal",
                title="Regulatory and clinical signal",
                stage_tags=["construct-output", "ai-review"],
                species_tags=["human", "dog", "cross-species"],
                queries={"clinical_trials": ["personalized neoantigen cancer vaccine"]},
                priority=3,
                paul_core=False,
            )
        ]
    )
    context = make_context(tmp_path, config=config, client=client)

    adapter = research.ClinicalTrialsAdapter()
    items = adapter.broad_fetch(context)

    assert len(items) == 1
    item = items[0]
    assert item.canonical_id == "nct:NCT03794128"
    assert item.updated_at == "2026-04-08"

    deepened = adapter.deepen(context, item)
    assert "manufacturing feasibility" in deepened.summary.lower()


@pytest.mark.parametrize(
    ("watch_id", "fixture_name", "expected_version", "expected_date"),
    [
        ("ipd-mhc", "ipd_mhc.html", "3.16.0.0", "2026-01-03"),
        ("dog10k", "dog10k.html", None, "2024-10-22"),
        ("pvactools-docs", "pvactools.html", "6.1.0", None),
        ("ensembl-vep-docs", "ensembl_vep.html", "115", "2025-09-01"),
        ("gatk-mutect2-docs", "gatk_mutect2.html", "27208", "2025-01-04"),
        ("netmhcpan-docs", "netmhcpan.html", "4.2", None),
        ("netmhciipan-docs", "netmhciipan.html", "4.1", None),
    ],
)
def test_watch_page_adapter_extracts_versions_from_official_pages(
    tmp_path: Path,
    watch_id: str,
    fixture_name: str,
    expected_version: str | None,
    expected_date: str | None,
):
    watch_page = research.WatchPageConfig(
        id=watch_id,
        kind="official_tool" if "docs" in watch_id else "official_resource",
        title=watch_id,
        url=f"https://example.org/{watch_id}",
        topic_ids=["neoantigen-prediction"],
        stage_tags=["neoantigen-prediction"],
        species_tags=["dog", "cross-species"],
        version_pattern={
            "ipd-mhc": "Release\\s+([0-9.]+\\.0)",
            "dog10k": None,
            "pvactools-docs": "pVACtools\\s+([0-9]+(?:\\.[0-9]+)+)",
            "ensembl-vep-docs": "Ensembl release\\s*([0-9]+)",
            "gatk-mutect2-docs": "<!--\\s*v([0-9]+)\\s*-->",
            "netmhcpan-docs": "NetMHCpan\\s*([0-9]+(?:\\.[0-9]+)+)",
            "netmhciipan-docs": "NetMHCIIpan\\s*([0-9]+(?:\\.[0-9]+)+)",
        }[watch_id],
        updated_pattern={
            "ipd-mhc": "Release\\s+[0-9.]+\\.0.*?(\\d{1,2}\\s+[A-Za-z]+\\s+\\d{4})",
            "dog10k": "published in .*? on ([A-Za-z]+ \\d{1,2}, \\d{4})",
            "pvactools-docs": None,
            "ensembl-vep-docs": "Ensembl release\\s*\\d+\\s*-\\s*([A-Za-z]+\\s+\\d{4})",
            "gatk-mutect2-docs": "datetime=\"([^\"]+)\"",
            "netmhcpan-docs": None,
            "netmhciipan-docs": None,
        }[watch_id],
        title_pattern="<title>(.*?)</title>",
        summary_template="Observed {title} version {version} updated {updated}.",
    )
    client = FixtureClient({"watch-page": read_fixture(fixture_name)})
    config = make_config(
        topics=[make_topic(topic_id="neoantigen-prediction", title="Neoantigen prediction", stage_tags=["neoantigen-prediction"], species_tags=["dog"], queries={})],
        watch_pages=[watch_page],
    )
    context = make_context(tmp_path, config=config, client=client)

    item = research.WatchPageAdapter().broad_fetch(context)[0]

    assert item.metadata.get("version") == expected_version
    assert item.updated_at == expected_date


def test_dedupe_items_merges_on_doi_pmid_pmcid_url_and_version():
    article_a = make_item(
        canonical_id="pmid:40698840",
        canonical_url="https://pubmed.ncbi.nlm.nih.gov/40698840/",
        source_type="peer_reviewed_literature",
        evidence_status="peer-reviewed",
        metadata={
            "topic_ids": ["neoantigen-prediction"],
            "pmid": "40698840",
            "doi": "10.1002/advs.202501234",
            "pmcid": "PMC12936311",
        },
    )
    article_b = make_item(
        canonical_id="doi:10.1002/advs.202501234",
        canonical_url="https://doi.org/10.1002/advs.202501234",
        source_type="preprint",
        evidence_status="preprint",
        metadata={
            "topic_ids": ["neoantigen-prediction"],
            "doi": "10.1002/advs.202501234",
            "pmcid": "PMC12936311",
        },
    )
    article_c = make_item(
        canonical_id="europepmc:PPR:PPR999999",
        canonical_url="https://pubmed.ncbi.nlm.nih.gov/40698840/",
        source_type="preprint",
        evidence_status="preprint",
        metadata={"topic_ids": ["neoantigen-prediction"], "pmcid": "PMC12936311"},
    )
    watch_a = make_item(
        canonical_id="pvactools-docs:6.1.0",
        canonical_url="https://pvactools.readthedocs.io/",
        source_type="official_tool",
        evidence_status="official-update",
        metadata={"topic_ids": ["neoantigen-prediction"], "version": "6.1.0"},
    )
    watch_b = make_item(
        canonical_id="pvactools-docs",
        canonical_url="https://pvactools.readthedocs.io/",
        source_type="official_tool",
        evidence_status="official-update",
        metadata={"topic_ids": ["neoantigen-prediction"], "version": "6.1.0"},
    )

    merged = research.dedupe_items([article_a, article_b, article_c, watch_a, watch_b])

    assert len(merged) == 2
    merged_ids = {item.canonical_id for item in merged}
    assert "doi:10.1002/advs.202501234" in merged_ids
    assert "pvactools-docs:6.1.0" in merged_ids


def test_brief_and_backlog_render_match_golden_output(tmp_path: Path):
    config = make_config(
        topics=[
            make_topic(
                topic_id="neoantigen-prediction",
                title="Neoantigen prediction",
                stage_tags=["neoantigen-prediction"],
                species_tags=["dog", "cross-species"],
                queries={},
            )
        ]
    )
    context = make_context(tmp_path, config=config, client=FixtureClient({}))
    findings = [
        research.ResearchFinding(
            source_type="official_tool",
            canonical_id="pvactools-docs:6.1.0",
            canonical_url="https://pvactools.readthedocs.io/",
            title="pVACtools docs drift",
            published_at=None,
            updated_at=None,
            stage_tags=["neoantigen-prediction"],
            species_tags=["dog", "cross-species"],
            evidence_status="official-update",
            summary="Official docs now advertise pVACtools 6.1.0.",
            confidence=0.91,
            novelty=1.0,
            pipeline_impact=0.88,
            recommended_action="Compare docs drift against repo assumptions.",
            bucket="implement",
            why_it_matters="Touches neoantigen-prediction for dog and cross-species work.",
            next_action="Open an implementation issue or update the active pipeline assumptions.",
            supporting_ids=["version:pvactools-docs:6.1.0"],
            topic_ids=["neoantigen-prediction"],
            score=0.925,
        )
    ]
    items = [
        make_item(
            canonical_id="pvactools-docs:6.1.0",
            canonical_url="https://pvactools.readthedocs.io/",
            source_type="official_tool",
            evidence_status="official-update",
            title="pVACtools docs drift",
        )
    ]

    brief = research.render_daily_brief(context, items, findings, [])
    backlog = research.render_backlog(findings)

    assert brief == (
        "# Daily Research Brief - 2026-04-12\n"
        "\n"
        "- Window: 2026-03-29 to 2026-04-12\n"
        "- Normalized items: 1\n"
        "- Promoted findings: 1 highlighted, 1 total candidates reviewed\n"
        "\n"
        "## Top Findings\n"
        "- [pVACtools docs drift](https://pvactools.readthedocs.io/) [implement] stages=neoantigen-prediction species=dog, cross-species\n"
        "  Why it matters: Touches neoantigen-prediction for dog and cross-species work.\n"
        "  Next action: Open an implementation issue or update the active pipeline assumptions.\n"
        "\n"
        "## Watch Signals\n"
        "- pVACtools docs drift: Useful signal for cancerstudio. (confidence 0.80, impact 0.80)\n"
        "\n"
        "## Source Failures\n"
        "- None.\n"
    )
    assert backlog == (
        "# Research Backlog\n"
        "\n"
        "## Implement\n"
        "- [pVACtools docs drift](https://pvactools.readthedocs.io/) stages=neoantigen-prediction species=dog, cross-species\n"
        "  Why: Touches neoantigen-prediction for dog and cross-species work.\n"
        "  Next: Open an implementation issue or update the active pipeline assumptions.\n"
        "\n"
        "## Benchmark\n"
        "- None.\n"
        "\n"
        "## Monitor\n"
        "- None.\n"
        "\n"
        "## Defer\n"
        "- None.\n"
    )


def test_run_research_cycle_survives_partial_source_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_root = tmp_path / "repo"
    (repo_root / "research" / "config").mkdir(parents=True)
    (repo_root / "research" / "config" / "taxonomy.json").write_text(
        json.dumps({"schemaVersion": 1, "stageTags": [], "speciesTags": [], "defaults": {}, "topics": [], "watchPages": []}),
        encoding="utf-8",
    )
    (repo_root / "research" / "config" / "promotion_rules.json").write_text(
        json.dumps(
            {
                "sourceWeights": {},
                "evidenceConfidence": {},
                "stagePriorityBoosts": {},
                "speciesPriorityBoosts": {},
                "bucketThresholds": {"implement": 0.82, "benchmark": 0.67, "monitor": 0.45},
                "strongPreprintThreshold": 0.9,
                "topFindingCount": 5,
                "corroboratedSourcesNeeded": 2,
            }
        ),
        encoding="utf-8",
    )

    class FailingAdapter(research.SourceAdapter):
        adapter_id = "failing"

        def broad_fetch(self, context):
            raise RuntimeError("upstream timeout")

    class StaticAdapter(research.SourceAdapter):
        adapter_id = "static"

        def broad_fetch(self, context):
            return [
                make_item(
                    canonical_id="doi:10.1/example",
                    canonical_url="https://doi.org/10.1/example",
                    source_type="official_resource",
                    evidence_status="official-update",
                    metadata={"topic_ids": []},
                )
            ]

    monkeypatch.setattr(research, "build_adapters", lambda: [FailingAdapter(), StaticAdapter()])

    summary = research.run_research_cycle(
        repo_root=repo_root,
        run_date=date(2026, 4, 12),
        client=FixtureClient({}),
        write_outputs_flag=True,
    )

    brief_text = summary.brief_path.read_text(encoding="utf-8")
    assert "Source Failures" in brief_text
    assert "failing: upstream timeout" in brief_text


def test_run_research_cycle_generates_expected_acceptance_signals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo_root = tmp_path / "repo"
    source_config_root = Path(__file__).resolve().parents[2] / "research" / "config"
    target_config_root = repo_root / "research" / "config"
    target_config_root.mkdir(parents=True)
    for filename in ("taxonomy.json", "promotion_rules.json"):
        (target_config_root / filename).write_text(
            (source_config_root / filename).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    client = FixtureClient(
        {
            "pubmed-esearch": read_fixture("pubmed_esearch.json"),
            "pubmed-esummary": read_fixture("pubmed_esummary.json"),
            "pubmed-efetch": read_fixture("pubmed_efetch.xml"),
            "europepmc-search": read_fixture("europepmc_search.json"),
            "europepmc-core": read_fixture("europepmc_core.json"),
            "clinicaltrials-version": read_fixture("clinical_trials_version.json"),
            "clinicaltrials-search": read_fixture("clinical_trials_search.json"),
            "clinicaltrials-detail": read_fixture("clinical_trials_detail.json"),
            "watch-page-ipd-mhc": read_fixture("ipd_mhc.html"),
            "watch-page-dog10k": read_fixture("dog10k.html"),
            "watch-page-pvactools-docs": read_fixture("pvactools.html"),
            "watch-page-ensembl-vep-docs": read_fixture("ensembl_vep.html"),
            "watch-page-gatk-mutect2-docs": read_fixture("gatk_mutect2.html"),
            "watch-page-netmhcpan-docs": read_fixture("netmhcpan.html"),
            "watch-page-netmhciipan-docs": read_fixture("netmhciipan.html"),
        }
    )

    original_get_text = client.get_text

    def get_text(url, *, params=None, headers=None, cache_key=None):
        if cache_key and cache_key.startswith("watch-page-"):
            return original_get_text(url, params=params, headers=headers, cache_key=cache_key)
        return original_get_text(url, params=params, headers=headers, cache_key=cache_key)

    client.get_text = get_text

    summary = research.run_research_cycle(
        repo_root=repo_root,
        run_date=date(2026, 4, 12),
        client=client,
        write_outputs_flag=True,
    )

    findings_payload = json.loads(summary.findings_path.read_text(encoding="utf-8"))
    findings = findings_payload["findings"]
    titles = {finding["title"] for finding in findings}

    assert "IPD-MHC Database" in titles
    assert "pVACtools" in titles
    assert any("Rapid-Turnaround Co-Administration" in title for title in titles)
    neoantigen_finding = next(
        finding for finding in findings if "Rapid-Turnaround Co-Administration" in finding["title"]
    )
    assert "neoantigen-prediction" in neoantigen_finding["stage_tags"]

    backlog_text = summary.backlog_path.read_text(encoding="utf-8")
    assert "IPD-MHC Database" in backlog_text
    assert "pVACtools" in backlog_text
