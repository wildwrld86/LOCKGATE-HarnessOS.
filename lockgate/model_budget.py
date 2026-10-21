"""Trusted resource policy shared by the host adapter and its worker."""
import json
import re
from dataclasses import dataclass
from pathlib import Path


def model_identifier(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/-]{0,119}', value) is not None


class ProviderError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ModelBudget:
    allowed_models: tuple[str, ...]
    max_calls: int
    wall_time_seconds: int
    max_completion_tokens: int
    max_request_bytes: int
    max_response_bytes: int

    def __post_init__(self) -> None:
        if (not isinstance(self.allowed_models, tuple) or not 1 <= len(self.allowed_models) <= 5
                or not all(model_identifier(x) for x in self.allowed_models)
                or len(set(self.allowed_models)) != len(self.allowed_models)):
            raise ValueError('Invalid model allowlist')
        bounds = ((self.max_calls, 1, 1), (self.wall_time_seconds, 1, 30),
                  (self.max_completion_tokens, 64, 2048), (self.max_request_bytes, 1024, 65536),
                  (self.max_response_bytes, 1024, 131072))
        if any(type(value) is not int or not lo <= value <= hi for value, lo, hi in bounds):
            raise ValueError('Invalid model budget')

    @classmethod
    def from_dict(cls, value: dict) -> 'ModelBudget':
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError('Invalid model budget fields')
        if not isinstance(value['allowed_models'], (list, tuple)):
            raise ValueError('Invalid model allowlist')
        return cls(**{**value, 'allowed_models': tuple(value['allowed_models'])})

    @classmethod
    def from_file(cls, path: str | Path) -> 'ModelBudget':
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))
