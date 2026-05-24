from abc import ABC, abstractmethod
from typing import Any, Dict, List


class IFeatureFlagProvider(ABC):
    """Abstract interface for feature flag providers (e.g., GrowthBook)."""

    @abstractmethod
    async def fetch_flags(self, environment: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def update_flag(self, environment: str, flag_key: str, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        pass
