from pydantic import BaseModel
from typing import List, Literal, Dict, Any, Optional


class PromotionValidateRequest(BaseModel):
    market: str
    from_env: str
    to_env: str
    flags_to_promote: List[str]


class ConflictItem(BaseModel):
    flag_key: str
    source_rules: Optional[Dict[str, Any]] = None
    target_rules: Optional[Dict[str, Any]] = None
    source_enabled: bool = False
    target_enabled: bool = False


class PromotionValidateResponse(BaseModel):
    batch_id: str
    conflicts: List[ConflictItem]


class ResolutionItem(BaseModel):
    flag_key: str
    decision: Literal["keep_target", "use_source"]
    force: Optional[bool] = False


class ResolveConflictsRequest(BaseModel):
    batch_id: str
    resolutions: List[ResolutionItem]


class ResolveConflictsResponse(BaseModel):
    batch_id: str
    status: str


class ExecuteRequest(BaseModel):
    batch_id: str
    executed_by: Optional[str] = None


class ExecuteResultItem(BaseModel):
    flag_key: str
    applied: bool
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ExecuteResponse(BaseModel):
    batch_id: str
    status: str
    results: List[ExecuteResultItem]
