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
