from abc import ABC, abstractmethod
from typing import Any


class ERPProvider(ABC):
    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_company_info(self) -> dict[str, Any]:
        pass
