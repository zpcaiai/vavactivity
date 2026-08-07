"""Public schema compatibility and code-generation contracts."""

from vav_skill_contracts.codegen import GeneratedContracts, generate_contracts
from vav_skill_contracts.compatibility import ContractChange, ContractDiff, compare_schemas

__all__ = [
    "ContractChange",
    "ContractDiff",
    "GeneratedContracts",
    "compare_schemas",
    "generate_contracts",
]
