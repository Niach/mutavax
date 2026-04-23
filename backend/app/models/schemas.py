from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PipelineStageId(str, Enum):
    INGESTION = "ingestion"
    ALIGNMENT = "alignment"
    VARIANT_CALLING = "variant-calling"
    ANNOTATION = "annotation"
    NEOANTIGEN_PREDICTION = "neoantigen-prediction"
    EPITOPE_SELECTION = "epitope-selection"
    CONSTRUCT_DESIGN = "construct-design"
    STRUCTURE_PREDICTION = "structure-prediction"
    CONSTRUCT_OUTPUT = "construct-output"
    AI_REVIEW = "ai-review"


class WorkspaceSpecies(str, Enum):
    HUMAN = "human"
    DOG = "dog"
    CAT = "cat"


class ReferencePreset(str, Enum):
    GRCH38 = "grch38"
    CANFAM4 = "canfam4"
    FELCAT9 = "felcat9"


class SampleLane(str, Enum):
    TUMOR = "tumor"
    NORMAL = "normal"


class WorkspaceFileFormat(str, Enum):
    FASTQ = "fastq"
    BAM = "bam"
    CRAM = "cram"


class WorkspaceFileRole(str, Enum):
    SOURCE = "source"
    CANONICAL = "canonical"


class WorkspaceFileStatus(str, Enum):
    UPLOADED = "uploaded"
    NORMALIZING = "normalizing"
    READY = "ready"
    FAILED = "failed"


class IngestionStatus(str, Enum):
    EMPTY = "empty"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    NORMALIZING = "normalizing"
    READY = "ready"
    FAILED = "failed"


class IngestionProgressPhase(str, Enum):
    VALIDATING = "validating"
    REFERENCING = "referencing"
    CONCATENATING = "concatenating"
    COMPRESSING = "compressing"
    EXTRACTING = "extracting"
    FINALIZING = "finalizing"


class ReadPair(str, Enum):
    R1 = "R1"
    R2 = "R2"
    SE = "SE"
    UNKNOWN = "unknown"


class ReadLayout(str, Enum):
    PAIRED = "paired"
    SINGLE = "single"


class AlignmentStageStatus(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class AlignmentRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class AlignmentRuntimePhase(str, Enum):
    PREPARING_REFERENCE = "preparing_reference"
    ALIGNING = "aligning"
    FINALIZING = "finalizing"


class QcVerdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class AlignmentArtifactKind(str, Enum):
    BAM = "bam"
    BAI = "bai"
    FLAGSTAT = "flagstat"
    IDXSTATS = "idxstats"
    STATS = "stats"


class WorkspaceAnalysisProfileResponse(BaseModel):
    reference_preset: Optional[ReferencePreset] = None
    reference_override: Optional[str] = None


class WorkspaceFileResponse(BaseModel):
    id: str
    batch_id: str
    source_file_id: Optional[str] = None
    sample_lane: SampleLane
    filename: str
    format: WorkspaceFileFormat
    file_role: WorkspaceFileRole
    status: WorkspaceFileStatus
    size_bytes: int
    uploaded_at: str
    read_pair: ReadPair
    source_path: Optional[str] = None
    managed_path: Optional[str] = None
    error: Optional[str] = None


class IngestionLaneProgressResponse(BaseModel):
    phase: IngestionProgressPhase
    current_filename: Optional[str] = None
    bytes_processed: Optional[int] = None
    total_bytes: Optional[int] = None
    throughput_bytes_per_sec: Optional[float] = None
    eta_seconds: Optional[float] = None
    percent: Optional[float] = None


class IngestionLaneSummaryResponse(BaseModel):
    active_batch_id: Optional[str] = None
    sample_lane: SampleLane
    status: IngestionStatus = IngestionStatus.EMPTY
    ready_for_alignment: bool = False
    source_file_count: int = 0
    canonical_file_count: int = 0
    missing_pairs: List[ReadPair] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)
    read_layout: Optional[ReadLayout] = None
    updated_at: Optional[str] = None
    progress: Optional[IngestionLaneProgressResponse] = None


class IngestionSummaryResponse(BaseModel):
    status: IngestionStatus = IngestionStatus.EMPTY
    ready_for_alignment: bool = False
    lanes: Dict[SampleLane, IngestionLaneSummaryResponse] = Field(default_factory=dict)


class WorkspaceCreateRequest(BaseModel):
    display_name: str
    species: WorkspaceSpecies = WorkspaceSpecies.HUMAN


class WorkspaceResponse(BaseModel):
    id: str
    display_name: str
    species: WorkspaceSpecies
    analysis_profile: WorkspaceAnalysisProfileResponse = Field(
        default_factory=WorkspaceAnalysisProfileResponse
    )
    active_stage: PipelineStageId = PipelineStageId.INGESTION
    created_at: str
    updated_at: str
    ingestion: IngestionSummaryResponse = Field(default_factory=IngestionSummaryResponse)
    files: List[WorkspaceFileResponse] = Field(default_factory=list)


class ActiveStageUpdateRequest(BaseModel):
    active_stage: PipelineStageId


class WorkspaceAnalysisProfileUpdateRequest(BaseModel):
    reference_preset: Optional[ReferencePreset] = None
    reference_override: Optional[str] = None


class LocalFileRegistrationRequest(BaseModel):
    sample_lane: SampleLane
    paths: List[str] = Field(default_factory=list)


class FastqReadPreview(BaseModel):
    header: str
    sequence: str
    quality: str
    length: int
    gc_percent: float
    mean_quality: float


class SampledReadStats(BaseModel):
    sampled_read_count: int
    average_read_length: float
    sampled_gc_percent: float


class IngestionLanePreviewResponse(BaseModel):
    workspace_id: str
    sample_lane: SampleLane
    batch_id: str
    source: Literal["canonical-fastq"] = "canonical-fastq"
    read_layout: ReadLayout = ReadLayout.PAIRED
    reads: Dict[ReadPair, List[FastqReadPreview]] = Field(default_factory=dict)
    stats: SampledReadStats


class AlignmentLaneMetricsResponse(BaseModel):
    sample_lane: SampleLane
    total_reads: int = 0
    mapped_reads: int = 0
    mapped_percent: float = 0.0
    properly_paired_percent: Optional[float] = None
    duplicate_percent: Optional[float] = None
    mean_insert_size: Optional[float] = None


class AlignmentArtifactResponse(BaseModel):
    id: str
    artifact_kind: AlignmentArtifactKind
    sample_lane: Optional[SampleLane] = None
    filename: str
    size_bytes: int
    download_path: str
    local_path: Optional[str] = None


class ChunkProgressPhase(str, Enum):
    SPLITTING = "splitting"
    ALIGNING = "aligning"
    MERGING = "merging"


class ChunkProgressStateResponse(BaseModel):
    phase: ChunkProgressPhase
    total_chunks: int = 0
    completed_chunks: int = 0
    active_chunks: int = 0


class AlignmentRunResponse(BaseModel):
    id: str
    status: AlignmentRunStatus
    progress: float = 0.0
    reference_preset: Optional[ReferencePreset] = None
    reference_override: Optional[str] = None
    reference_label: Optional[str] = None
    runtime_phase: Optional[AlignmentRuntimePhase] = None
    qc_verdict: Optional[QcVerdict] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    blocking_reason: Optional[str] = None
    error: Optional[str] = None
    command_log: List[str] = Field(default_factory=list)
    recent_log_tail: List[str] = Field(default_factory=list)
    last_activity_at: Optional[str] = None
    eta_seconds: Optional[float] = None
    progress_components: Dict[str, float] = Field(default_factory=dict)
    expected_total_per_lane: Dict[SampleLane, int] = Field(default_factory=dict)
    lane_metrics: Dict[SampleLane, AlignmentLaneMetricsResponse] = Field(
        default_factory=dict
    )
    chunk_progress: Dict[SampleLane, ChunkProgressStateResponse] = Field(
        default_factory=dict
    )
    artifacts: List[AlignmentArtifactResponse] = Field(default_factory=list)


class AlignmentStageSummaryResponse(BaseModel):
    workspace_id: str
    status: AlignmentStageStatus
    blocking_reason: Optional[str] = None
    analysis_profile: WorkspaceAnalysisProfileResponse = Field(
        default_factory=WorkspaceAnalysisProfileResponse
    )
    qc_verdict: Optional[QcVerdict] = None
    ready_for_variant_calling: bool = False
    latest_run: Optional[AlignmentRunResponse] = None
    lane_metrics: Dict[SampleLane, Optional[AlignmentLaneMetricsResponse]] = Field(
        default_factory=dict
    )
    artifacts: List[AlignmentArtifactResponse] = Field(default_factory=list)


class VariantCallingRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class VariantCallingStageStatus(str, Enum):
    BLOCKED = "blocked"
    SCAFFOLDED = "scaffolded"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class VariantCallingRuntimePhase(str, Enum):
    PREPARING_REFERENCE = "preparing_reference"
    CALLING = "calling"
    FILTERING = "filtering"
    FINALIZING = "finalizing"


class VariantCallingArtifactKind(str, Enum):
    VCF = "vcf"
    VCF_INDEX = "tbi"
    STATS = "stats"


class VariantTypeKind(str, Enum):
    SNV = "snv"
    INSERTION = "insertion"
    DELETION = "deletion"
    MNV = "mnv"


class ChromosomeMetricsEntry(BaseModel):
    chromosome: str
    length: int = 0
    total: int = 0
    pass_count: int = 0
    snv_count: int = 0
    indel_count: int = 0


class FilterBreakdownEntry(BaseModel):
    name: str
    count: int
    is_pass: bool = False


class VafHistogramBin(BaseModel):
    bin_start: float
    bin_end: float
    count: int


class TopVariantEntry(BaseModel):
    chromosome: str
    position: int
    ref: str
    alt: str
    variant_type: VariantTypeKind
    filter: str
    is_pass: bool
    tumor_vaf: Optional[float] = None
    tumor_depth: Optional[int] = None
    normal_depth: Optional[int] = None


class VariantCallingMetricsResponse(BaseModel):
    total_variants: int = 0
    snv_count: int = 0
    indel_count: int = 0
    insertion_count: int = 0
    deletion_count: int = 0
    mnv_count: int = 0
    pass_count: int = 0
    pass_snv_count: int = 0
    pass_indel_count: int = 0
    ti_tv_ratio: Optional[float] = None
    transitions: int = 0
    transversions: int = 0
    mean_vaf: Optional[float] = None
    median_vaf: Optional[float] = None
    tumor_mean_depth: Optional[float] = None
    normal_mean_depth: Optional[float] = None
    tumor_sample: Optional[str] = None
    normal_sample: Optional[str] = None
    reference_label: Optional[str] = None
    pon_label: Optional[str] = None
    per_chromosome: List[ChromosomeMetricsEntry] = Field(default_factory=list)
    filter_breakdown: List[FilterBreakdownEntry] = Field(default_factory=list)
    vaf_histogram: List[VafHistogramBin] = Field(default_factory=list)
    top_variants: List[TopVariantEntry] = Field(default_factory=list)


class VariantCallingArtifactResponse(BaseModel):
    id: str
    artifact_kind: VariantCallingArtifactKind
    filename: str
    size_bytes: int
    download_path: str
    local_path: Optional[str] = None


VariantCallingAccelerationMode = Literal["gpu_parabricks", "cpu_gatk"]


class VariantCallingRunResponse(BaseModel):
    id: str
    status: VariantCallingRunStatus
    progress: float = 0.0
    runtime_phase: Optional[VariantCallingRuntimePhase] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    blocking_reason: Optional[str] = None
    error: Optional[str] = None
    command_log: List[str] = Field(default_factory=list)
    metrics: Optional[VariantCallingMetricsResponse] = None
    artifacts: List[VariantCallingArtifactResponse] = Field(default_factory=list)
    completed_shards: int = 0
    total_shards: int = 0
    acceleration_mode: VariantCallingAccelerationMode = "cpu_gatk"


class VariantCallingStageSummaryResponse(BaseModel):
    workspace_id: str
    status: VariantCallingStageStatus
    blocking_reason: Optional[str] = None
    ready_for_annotation: bool = False
    latest_run: Optional[VariantCallingRunResponse] = None
    artifacts: List[VariantCallingArtifactResponse] = Field(default_factory=list)


class AnnotationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class AnnotationStageStatus(str, Enum):
    BLOCKED = "blocked"
    SCAFFOLDED = "scaffolded"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class AnnotationRuntimePhase(str, Enum):
    INSTALLING_CACHE = "installing_cache"
    ANNOTATING = "annotating"
    SUMMARIZING = "summarizing"
    FINALIZING = "finalizing"


class AnnotationArtifactKind(str, Enum):
    ANNOTATED_VCF = "annotated_vcf"
    ANNOTATED_VCF_INDEX = "annotated_vcf_index"
    VEP_SUMMARY = "vep_summary"
    VEP_WARNINGS = "vep_warnings"


AnnotationImpactTier = Literal["HIGH", "MODERATE", "LOW", "MODIFIER"]


class AnnotationConsequenceEntry(BaseModel):
    term: str
    label: str
    count: int


class GeneFocusVariant(BaseModel):
    chromosome: str
    position: int
    protein_position: Optional[int] = None
    hgvsp: Optional[str] = None
    hgvsc: Optional[str] = None
    consequence: str
    impact: AnnotationImpactTier
    tumor_vaf: Optional[float] = None


class CancerGeneHit(BaseModel):
    symbol: str
    role: str
    variant_count: int
    highest_impact: AnnotationImpactTier
    top_hgvsp: Optional[str] = None
    top_consequence: Optional[str] = None
    # Full per-gene variant bundle so the frontend can paint the lollipop
    # for any cancer-gene card the user clicks — not just the top focus.
    transcript_id: Optional[str] = None
    protein_length: Optional[int] = None
    variants: List[GeneFocusVariant] = Field(default_factory=list)


class ProteinDomain(BaseModel):
    start: int
    end: int
    label: str
    # "catalytic" flags the business-end band that variant hotspots tend to
    # cluster in (kinase, DNA-binding, etc.). Rendered in the theme accent
    # colour; everything else renders neutral grey.
    kind: Optional[Literal["catalytic", "neutral"]] = None


class GeneFocus(BaseModel):
    symbol: str
    role: Optional[str] = None
    transcript_id: Optional[str] = None
    protein_length: Optional[int] = None
    variants: List[GeneFocusVariant] = Field(default_factory=list)
    domains: Optional[List[ProteinDomain]] = None


class GeneDomainsResponse(BaseModel):
    symbol: str
    transcript_id: Optional[str] = None
    protein_length: Optional[int] = None
    domains: List[ProteinDomain] = Field(default_factory=list)


class AnnotatedVariantEntry(BaseModel):
    chromosome: str
    position: int
    ref: str
    alt: str
    gene_symbol: Optional[str] = None
    transcript_id: Optional[str] = None
    consequence: str
    consequence_label: str
    impact: AnnotationImpactTier
    hgvsc: Optional[str] = None
    hgvsp: Optional[str] = None
    protein_position: Optional[int] = None
    tumor_vaf: Optional[float] = None
    in_cancer_gene: bool = False


class AnnotationMetricsResponse(BaseModel):
    total_variants: int = 0
    annotated_variants: int = 0
    by_impact: Dict[str, int] = Field(default_factory=dict)
    by_consequence: List[AnnotationConsequenceEntry] = Field(default_factory=list)
    cancer_gene_hits: List[CancerGeneHit] = Field(default_factory=list)
    cancer_gene_variant_count: int = 0
    top_gene_focus: Optional[GeneFocus] = None
    top_variants: List[AnnotatedVariantEntry] = Field(default_factory=list)
    reference_label: Optional[str] = None
    species_label: Optional[str] = None
    vep_release: Optional[str] = None


class AnnotationArtifactResponse(BaseModel):
    id: str
    artifact_kind: AnnotationArtifactKind
    filename: str
    size_bytes: int
    download_path: str
    local_path: Optional[str] = None


class AnnotationRunResponse(BaseModel):
    id: str
    status: AnnotationRunStatus
    progress: float = 0.0
    runtime_phase: Optional[AnnotationRuntimePhase] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    blocking_reason: Optional[str] = None
    error: Optional[str] = None
    command_log: List[str] = Field(default_factory=list)
    metrics: Optional[AnnotationMetricsResponse] = None
    artifacts: List[AnnotationArtifactResponse] = Field(default_factory=list)
    cache_pending: bool = False
    cache_species_label: Optional[str] = None
    cache_expected_megabytes: Optional[int] = None


class AnnotationStageSummaryResponse(BaseModel):
    workspace_id: str
    status: AnnotationStageStatus
    blocking_reason: Optional[str] = None
    ready_for_neoantigen: bool = False
    latest_run: Optional[AnnotationRunResponse] = None
    artifacts: List[AnnotationArtifactResponse] = Field(default_factory=list)


class DLAAllele(BaseModel):
    name: str
    locus: str
    sequence: Optional[str] = None
    has_binding_data: bool = False


class Neoantigen(BaseModel):
    gene: str
    mutation: str
    peptide: str
    dla_allele: str
    binding_affinity_nm: float
    percentile_rank: float
    expression: Optional[float] = None
    clonal_vaf: Optional[float] = None


class VaccineConstruct(BaseModel):
    id: str
    name: str
    epitopes: List[Neoantigen]
    mrna_sequence: str
    protein_sequence: str
    five_prime_utr: str
    three_prime_utr: str
    poly_a_tail_length: int = 120
    codon_adaptation_index: float
    mfe_kcal: float
    gc_content: float


# --------------------------------------------------------------------------- #
# Stage 5 — Neoantigen prediction (pVACseq + NetMHCpan)
# --------------------------------------------------------------------------- #


class NeoantigenRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class NeoantigenStageStatus(str, Enum):
    BLOCKED = "blocked"
    SCAFFOLDED = "scaffolded"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class NeoantigenRuntimePhase(str, Enum):
    GENERATING_FASTA = "generating_fasta"
    RUNNING_CLASS_I = "running_class_i"
    RUNNING_CLASS_II = "running_class_ii"
    PARSING = "parsing"
    FINALIZING = "finalizing"


class NeoantigenArtifactKind(str, Enum):
    ALL_EPITOPES_CLASS_I = "all_epitopes_class_i"
    FILTERED_CLASS_I = "filtered_class_i"
    ALL_EPITOPES_CLASS_II = "all_epitopes_class_ii"
    FILTERED_CLASS_II = "filtered_class_ii"
    PVACSEQ_LOG = "pvacseq_log"


MhcClass = Literal["I", "II"]
AlleleTypingKind = Literal["typed", "inferred"]
BindingTier = Literal["strong", "moderate", "weak", "none"]


class PatientAllele(BaseModel):
    allele: str
    mhc_class: MhcClass = Field(..., alias="class")
    typing: AlleleTypingKind = "inferred"
    frequency: Optional[float] = None
    source: Optional[str] = None

    class Config:
        populate_by_name = True


class BindingBucket(BaseModel):
    key: BindingTier
    label: str
    threshold: str
    plain: str
    count: int


class HeatmapRow(BaseModel):
    seq: str
    gene: str
    mut: str
    length: int
    mhc_class: MhcClass = Field(..., alias="class")
    vaf: float
    ic50: List[float] = Field(default_factory=list)
    mut_pos: Optional[int] = None

    class Config:
        populate_by_name = True


class HeatmapData(BaseModel):
    alleles: List[str] = Field(default_factory=list)
    peptides: List[HeatmapRow] = Field(default_factory=list)


class FunnelStep(BaseModel):
    label: str
    count: int
    hint: str


class TopCandidate(BaseModel):
    seq: str
    gene: str
    mut: str
    length: int
    mhc_class: MhcClass = Field(..., alias="class")
    allele: str
    ic50: float
    wt_ic50: Optional[float] = None
    agretopicity: Optional[float] = None
    vaf: Optional[float] = None
    tpm: Optional[float] = None
    cancer_gene: bool = False
    strong: bool = False

    class Config:
        populate_by_name = True


class RejectedAllele(BaseModel):
    allele: str
    mhc_class: MhcClass = Field(..., alias="class")
    reason: str

    class Config:
        populate_by_name = True


class NeoantigenMetricsResponse(BaseModel):
    pvacseq_version: Optional[str] = None
    netmhcpan_version: Optional[str] = None
    netmhciipan_version: Optional[str] = None
    species_label: Optional[str] = None
    assembly: Optional[str] = None
    alleles: List[PatientAllele] = Field(default_factory=list)
    rejected_alleles: List[RejectedAllele] = Field(default_factory=list)
    annotated_variants: int = 0
    protein_changing_variants: int = 0
    peptides_generated: int = 0
    visible_candidates: int = 0
    class_i_count: int = 0
    class_ii_count: int = 0
    buckets: List[BindingBucket] = Field(default_factory=list)
    heatmap: HeatmapData = Field(default_factory=HeatmapData)
    funnel: List[FunnelStep] = Field(default_factory=list)
    top: List[TopCandidate] = Field(default_factory=list)


class NeoantigenArtifactResponse(BaseModel):
    id: str
    artifact_kind: NeoantigenArtifactKind
    filename: str
    size_bytes: int
    download_path: str
    local_path: Optional[str] = None


class NeoantigenRunResponse(BaseModel):
    id: str
    status: NeoantigenRunStatus
    progress: float = 0.0
    runtime_phase: Optional[NeoantigenRuntimePhase] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    blocking_reason: Optional[str] = None
    error: Optional[str] = None
    command_log: List[str] = Field(default_factory=list)
    metrics: Optional[NeoantigenMetricsResponse] = None
    artifacts: List[NeoantigenArtifactResponse] = Field(default_factory=list)


class NeoantigenStageSummaryResponse(BaseModel):
    workspace_id: str
    status: NeoantigenStageStatus
    blocking_reason: Optional[str] = None
    ready_for_epitope_selection: bool = False
    alleles: List[PatientAllele] = Field(default_factory=list)
    latest_run: Optional[NeoantigenRunResponse] = None
    artifacts: List[NeoantigenArtifactResponse] = Field(default_factory=list)


class NeoantigenAllelesUpdate(BaseModel):
    alleles: List[PatientAllele]


class EpitopeStageStatus(str, Enum):
    BLOCKED = "blocked"
    SCAFFOLDED = "scaffolded"
    COMPLETED = "completed"


EpitopeTier = Literal["strong", "moderate"]
EpitopeRisk = Literal["critical", "elevated", "mild"]


class EpitopeCandidateResponse(BaseModel):
    id: str
    seq: str
    gene: str
    mutation: str
    length: int
    mhc_class: MhcClass = Field(..., alias="class")
    allele_id: str
    ic50_nm: float
    agretopicity: float
    vaf: float
    tpm: float
    cancer_gene: bool = False
    driver_context: Optional[str] = None
    tier: EpitopeTier
    flags: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


class EpitopeSafetyFlagResponse(BaseModel):
    peptide_id: str
    self_hit: str
    identity: int
    risk: EpitopeRisk
    note: str


class EpitopeAlleleResponse(BaseModel):
    id: str
    mhc_class: MhcClass = Field(..., alias="class")
    color: str

    class Config:
        populate_by_name = True


class EpitopeStageSummaryResponse(BaseModel):
    workspace_id: str
    status: EpitopeStageStatus
    blocking_reason: Optional[str] = None
    candidates: List[EpitopeCandidateResponse] = Field(default_factory=list)
    safety: Dict[str, EpitopeSafetyFlagResponse] = Field(default_factory=dict)
    alleles: List[EpitopeAlleleResponse] = Field(default_factory=list)
    default_picks: List[str] = Field(default_factory=list)
    selection: List[str] = Field(default_factory=list)
    ready_for_construct_design: bool = False


class EpitopeSelectionUpdate(BaseModel):
    peptide_ids: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Stage 7 — mRNA construct design
# --------------------------------------------------------------------------- #


class ConstructDesignStatus(str, Enum):
    BLOCKED = "blocked"
    SCAFFOLDED = "scaffolded"
    CONFIRMED = "confirmed"


ConstructSegmentKind = Literal["signal", "linker", "peptide", "mitd"]


class ConstructDesignOptions(BaseModel):
    lambda_value: float = Field(0.65, alias="lambda", ge=0.0, le=1.0)
    signal: bool = True
    mitd: bool = True
    confirmed: bool = False

    class Config:
        populate_by_name = True


class ConstructSegment(BaseModel):
    kind: ConstructSegmentKind
    label: str
    sub: Optional[str] = None
    aa: str
    mhc_class: Optional[MhcClass] = Field(default=None, alias="class")
    peptide_id: Optional[str] = None
    color: Optional[str] = None

    class Config:
        populate_by_name = True


class ConstructFlanks(BaseModel):
    kozak: str
    utr5: str
    utr3: str
    poly_a: int
    signal_aa: str
    mitd_aa: str
    signal_why: str
    mitd_why: str


class ConstructMetrics(BaseModel):
    aa_len: int
    nt_len: int
    cai: float
    mfe: int
    gc: float
    full_mrna_nt: int
    mfe_per_nt: float


class ConstructManufacturingCheck(BaseModel):
    id: str
    label: str
    why: str
    status: Literal["pass", "warn", "fail"] = "pass"


class ConstructPreviewCodon(BaseModel):
    aa: str
    unopt: str
    opt: str
    swapped: bool


class ConstructPreview(BaseModel):
    gene: str
    mut: str
    codons: List[ConstructPreviewCodon]


class ConstructStageSummaryResponse(BaseModel):
    workspace_id: str
    status: ConstructDesignStatus
    blocking_reason: Optional[str] = None
    options: ConstructDesignOptions
    flanks: ConstructFlanks
    linkers: Dict[str, str]
    segments: List[ConstructSegment]
    aa_seq: str
    metrics: ConstructMetrics
    preview: ConstructPreview
    manufacturing_checks: List[ConstructManufacturingCheck]
    peptide_count: int
    ready_for_output: bool


class ConstructDesignUpdate(BaseModel):
    lambda_value: float = Field(..., alias="lambda", ge=0.0, le=1.0)
    signal: bool = True
    mitd: bool = True
    confirmed: bool = False

    class Config:
        populate_by_name = True


# --------------------------------------------------------------------------- #
# Stage 8 — Construct output
# --------------------------------------------------------------------------- #


class ConstructOutputStatus(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"
    RELEASED = "released"


ConstructRunKind = Literal[
    "utr5", "signal", "linker", "classI", "classII", "mitd", "stop", "utr3", "polyA"
]


class ConstructOutputRun(BaseModel):
    kind: ConstructRunKind
    label: str
    nt: str


class CmoOption(BaseModel):
    id: str
    name: str
    type: str
    tat: str
    cost: str
    good: List[str]


class DosingScheduleItem(BaseModel):
    when: str
    label: str
    what: str


class DosingProtocol(BaseModel):
    formulation: str
    route: str
    dose: str
    schedule: List[DosingScheduleItem]
    watch_for: List[str]


class AuditEntry(BaseModel):
    stage: str
    when: str
    who: str
    what: str
    kind: Literal["auto", "human"]


class ConstructOutputOrder(BaseModel):
    cmo_id: str
    po_number: str
    ordered_at: str


class ConstructOutputStageSummaryResponse(BaseModel):
    workspace_id: str
    status: ConstructOutputStatus
    blocking_reason: Optional[str] = None
    construct_id: str
    species: str
    version: str
    checksum: str
    released_at: Optional[str] = None
    released_by: Optional[str] = None
    runs: List[ConstructOutputRun]
    full_nt: str
    total_nt: int
    genbank: str
    cmo_options: List[CmoOption]
    selected_cmo: Optional[str] = None
    order: Optional[ConstructOutputOrder] = None
    dosing: DosingProtocol
    audit_trail: List[AuditEntry]


class ConstructOutputAction(BaseModel):
    action: Literal["select_cmo", "release"]
    cmo_id: Optional[str] = None


# ── Stage 9 — AI Review (Claude Opus 4.7 via LiteLLM) ──────────────────


class AiReviewFinding(BaseModel):
    severity: Literal["info", "note", "watch", "concern"]
    title: str
    detail: str


class AiReviewCategory(BaseModel):
    id: Literal["validity", "safety", "coverage", "manufact"]
    grade: Literal["A", "B", "C", "D"]
    verdict: Literal["pass", "watch", "concern"]
    summary: str
    findings: List[AiReviewFinding]


class AiReviewResult(BaseModel):
    verdict: Literal["approve", "approve_with_notes", "hold", "block"]
    confidence: int = Field(ge=0, le=100)
    headline: str
    letter: str
    categories: List[AiReviewCategory]
    top_risks: List[str]
    next_actions: List[str]
    reviewed_at: str
    model: str


class AiReviewDecision(BaseModel):
    kind: Literal["accept", "override"]
    at: str
    reason: Optional[str] = None


class AiReviewBriefPeptide(BaseModel):
    seq: str
    gene: str
    mut: Optional[str] = None
    cls: Optional[str] = None
    allele: Optional[str] = None
    ic50_nM: Optional[float] = None
    vaf: Optional[float] = None
    cancer_gene: bool = False
    driver: bool = False


class AiReviewBriefVariants(BaseModel):
    total: int
    pass_count: int = Field(alias="pass")
    snv: int
    indel: int
    median_vaf: Optional[float] = None
    tumor_depth: Optional[float] = None
    normal_depth: Optional[float] = None

    model_config = {"populate_by_name": True}


class AiReviewBriefCoverage(BaseModel):
    alleles: List[str]
    class_i: int = Field(alias="classI")
    class_ii: int = Field(alias="classII")
    unique_genes: List[str] = Field(alias="uniqueGenes")

    model_config = {"populate_by_name": True}


class AiReviewBriefConstruct(BaseModel):
    id: str
    version: str
    checksum: str
    aa_len: int = Field(alias="aaLen")
    nt_len: int = Field(alias="ntLen")
    cai: Optional[float] = None
    gc: Optional[float] = None
    mfe: Optional[float] = None

    model_config = {"populate_by_name": True}


class AiReviewCaseBrief(BaseModel):
    patient_id: str
    patient_name: str
    species: str
    reference: str
    variants: AiReviewBriefVariants
    shortlist: List[AiReviewBriefPeptide]
    coverage: AiReviewBriefCoverage
    construct_: AiReviewBriefConstruct = Field(alias="construct")

    model_config = {"populate_by_name": True}


class AiReviewStageStatus(str, Enum):
    BLOCKED = "blocked"
    SCAFFOLDED = "scaffolded"
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AiReviewStageSummaryResponse(BaseModel):
    workspace_id: str
    status: AiReviewStageStatus
    blocking_reason: Optional[str] = None
    model: str
    brief: Optional[AiReviewCaseBrief] = None
    result: Optional[AiReviewResult] = None
    decision: Optional[AiReviewDecision] = None
    last_error: Optional[str] = None


class AiReviewAction(BaseModel):
    action: Literal["run", "accept", "override", "reset"]
    reason: Optional[str] = None
