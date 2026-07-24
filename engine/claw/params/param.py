"""파라미터 정의(ParamDef) — 단위·설명·유효범위 메타데이터 보유 (구현 문서 §5.5).

메타데이터는 웹 UI 폼 자동 생성·입력 검증의 단일 원천이다.
"""

from dataclasses import dataclass


class ParamError(ValueError):
    """파라미터 정의·값 오류."""


@dataclass(frozen=True)
class ParamDef:
    name: str  # 점 네임스페이스: 'vehicle.mass.m0' (conventions.md §8)
    default: object
    unit: str  # SI 표기, 무차원은 '-'
    desc: str
    lo: float | None = None
    hi: float | None = None
    choices: tuple | None = None  # 열거형 (교체 컴포넌트 선택 등)

    def __post_init__(self):
        if not self.name or " " in self.name:
            raise ParamError(f"잘못된 파라미터 이름: {self.name!r}")
        self.validate(self.default)

    def validate(self, value):
        """값 검증 후 정규화된 값을 반환. 실패 시 ParamError."""
        if self.choices is not None:
            if value not in self.choices:
                raise ParamError(f"{self.name}: {value!r}는 허용값 {self.choices}에 없음")
            return value
        if isinstance(self.default, bool):
            if not isinstance(value, bool):
                raise ParamError(f"{self.name}: bool 필요, {type(value).__name__} 받음")
            return value
        if isinstance(self.default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ParamError(f"{self.name}: 수치 필요, {type(value).__name__} 받음")
            self._check_range(value)
            return float(value) if isinstance(self.default, float) else value
        if isinstance(self.default, str):
            if not isinstance(value, str):
                raise ParamError(f"{self.name}: 문자열 필요, {type(value).__name__} 받음")
            return value
        if isinstance(self.default, (list, tuple)):
            if not isinstance(value, (list, tuple)):
                raise ParamError(f"{self.name}: 배열 필요, {type(value).__name__} 받음")
            for v in value:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ParamError(f"{self.name}: 배열 원소는 수치여야 함, {v!r} 받음")
                self._check_range(v)
            return [float(v) for v in value]
        raise ParamError(f"{self.name}: 지원하지 않는 기본값 타입 {type(self.default).__name__}")

    def _check_range(self, v):
        if self.lo is not None and v < self.lo:
            raise ParamError(f"{self.name}: {v} < 하한 {self.lo}")
        if self.hi is not None and v > self.hi:
            raise ParamError(f"{self.name}: {v} > 상한 {self.hi}")

    def to_json_schema(self):
        """이 파라미터의 JSON 스키마 조각 — UI 폼 자동 생성용."""
        s = {"description": f"{self.desc} [{self.unit}]", "default": self.default}
        if self.choices is not None:
            s["enum"] = list(self.choices)
            return s
        if isinstance(self.default, bool):
            s["type"] = "boolean"
        elif isinstance(self.default, (int, float)):
            s["type"] = "integer" if isinstance(self.default, int) else "number"
            if self.lo is not None:
                s["minimum"] = self.lo
            if self.hi is not None:
                s["maximum"] = self.hi
        elif isinstance(self.default, str):
            s["type"] = "string"
        elif isinstance(self.default, (list, tuple)):
            items = {"type": "number"}
            if self.lo is not None:
                items["minimum"] = self.lo
            if self.hi is not None:
                items["maximum"] = self.hi
            s["type"] = "array"
            s["items"] = items
            s["default"] = list(self.default)
        return s
