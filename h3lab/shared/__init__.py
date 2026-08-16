"""Validated integration boundary for the standalone ComfyUI SDUI service."""

from h3lab.shared.client import SharedServiceClient
from h3lab.shared.generated_contract import WORKFLOW_ID

__all__ = ["WORKFLOW_ID", "SharedServiceClient"]
