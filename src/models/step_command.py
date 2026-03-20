from dataclasses import dataclass
from typing import List


@dataclass
class StepCommand:
    command: List[str]
    description: str
    log_prefix: str
