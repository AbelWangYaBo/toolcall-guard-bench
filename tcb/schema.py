"""极小 JSON Schema 校验(子集:type/enum/required/properties/additionalProperties)。

只校验场景声明所需的那点表达力;报告可读的错误子类型供分类。
"""
from __future__ import annotations

from typing import Any

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
}


def validate(value: Any, schema: dict | None) -> list[str]:
    """返回错误列表(空列表=通过)。错误消息带子类型前缀,如 enum_violation: ...。"""
    if not schema:
        return []
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type:
        python_types = _TYPES.get(expected_type)
        ok = isinstance(value, python_types) if python_types else True
        # bool 是 int 的子类,别把 true 当 integer 放过/误判
        if expected_type in ("integer", "number") and isinstance(value, bool):
            ok = False
        if not ok:
            return [f"type_mismatch: 期望 {expected_type},实际 {type(value).__name__}"]

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"enum_violation: {value!r} 不在 {schema['enum']!r} 内")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                errors.append(f"missing_required: 缺少参数 {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"unknown_field: 未声明的参数 {key!r}")
        for key, sub_value in value.items():
            sub_schema = properties.get(key)
            if sub_schema:
                errors.extend(validate(sub_value, sub_schema))

    return errors
