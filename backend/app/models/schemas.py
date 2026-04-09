from enum import Enum
from typing import Dict, List, Optional

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


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkspaceSpecies(str, Enum):
    HUMAN = "human"
    DOG = "dog"
    CAT = "cat"


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
    UPLOADED = "uploaded"
    NORMALIZING = "normalizing"
    READY = "ready"
    FAILED = "failed"


class ReadPair(str, Enum):
    R1 = "R1"
    R2 = "R2"
    UNKNOWN = "unknown"


class WorkspaceFileResponse(BaseModel):
    id: str
    batch_id: str
    source_file_id: Optional[str] = None
    filename: str
    format: WorkspaceFileFormat
    file_role: WorkspaceFileRole
    status: WorkspaceFileStatus
    size_bytes: int
    uploaded_at: str
    read_pair: ReadPair
    storage_key: str
    error: Optional[str] = None


class IngestionSummaryResponse(BaseModel):
    active_batch_id: Optional[str] = None
    status: IngestionStatus = IngestionStatus.EMPTY
    ready_for_alignment: bool = False
    source_file_count: int = 0
    canonical_file_count: int = 0
    missing_pairs: List[ReadPair] = Field(default_factory=list)
    updated_at: Optional[str] = None


class WorkspaceCreateRequest(BaseModel):
    display_name: str
    species: WorkspaceSpecies = WorkspaceSpecies.HUMAN


class WorkspaceResponse(BaseModel):
    id: str
    display_name: str
    species: WorkspaceSpecies
    active_stage: PipelineStageId = PipelineStageId.INGESTION
    created_at: str
    updated_at: str
    ingestion: IngestionSummaryResponse = Field(default_factory=IngestionSummaryResponse)
    files: List[WorkspaceFileResponse] = Field(default_factory=list)


class ActiveStageUpdateRequest(BaseModel):
    active_stage: PipelineStageId


class JobSubmitRequest(BaseModel):
    stage_id: PipelineStageId
    workspace_id: Optional[str] = None
    params: Dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    workspace_id: Optional[str] = None
    stage_id: PipelineStageId
    status: JobStatus
    progress: float = 0.0
    created_at: str
    updated_at: str
    error: Optional[str] = None
    result: Optional[Dict] = None


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
