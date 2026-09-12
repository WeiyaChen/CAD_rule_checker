# src/spatial/factory.py
"""按配置创建空间轮廓提取 / 空间类型识别算法实例。

流水线只依赖本模块，不直接引用任何具体算法类，因此新增同类型算法时
只需实现接口 + 注册，再改一处配置即可。
"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from .config import SpatialPipelineConfig
from .contracts import (
    ISpaceTypeClassifier,
    ISpatialContourExtractor,
    ITextLabelNormalizer,
)
from .registry import (
    CONTOUR_EXTRACTORS,
    SPACE_TYPE_CLASSIFIERS,
    TEXT_LABEL_NORMALIZERS,
    Registry,
)

#: 配置中用于指定文本归一化算法的键名。
TEXT_NORMALIZER_KEY = "text_normalizer"
TEXT_NORMALIZER_PARAMS_KEY = "text_normalizer_params"


def _default_llm_model() -> str | None:
    """未显式指定模型时回退到 ``settings.llm_model``。"""
    from src.config.config import settings

    return settings.llm_model


def create_contour_extractor(
    algorithm: str | None = None,
    params: Mapping[str, Any] | None = None,
    config: SpatialPipelineConfig | None = None,
) -> ISpatialContourExtractor:
    """创建空间轮廓提取算法实例。

    Args:
        algorithm: 算法注册名；``None`` 表示使用配置中的默认值。
        params: 覆盖配置的参数。
        config: 已解析的配置；``None`` 时从 ``settings.yaml`` 读取。
    """
    resolved = config or SpatialPipelineConfig.from_settings()
    merged = dict(resolved.contour_params)
    merged.update(params or {})
    return CONTOUR_EXTRACTORS.create(algorithm or resolved.contour_algorithm, params=merged)


def create_space_type_classifier(
    algorithm: str | None = None,
    params: Mapping[str, Any] | None = None,
    config: SpatialPipelineConfig | None = None,
    *,
    llm_client: Any = None,
    llm_model: str | None = None,
) -> ISpaceTypeClassifier:
    """创建空间类型识别算法实例。

    配置中的 ``text_normalizer`` / ``text_normalizer_params`` 会在这里被解析成
    实例后注入；未显式配置时交给算法自身的缺省值。
    """
    resolved = config or SpatialPipelineConfig.from_settings()
    merged = dict(resolved.classifier_params)
    merged.update(params or {})

    model = llm_model or _default_llm_model()
    services: dict[str, Any] = {"llm_client": llm_client, "llm_model": model}

    normalizer_name = merged.pop(TEXT_NORMALIZER_KEY, None)
    normalizer_params = merged.pop(TEXT_NORMALIZER_PARAMS_KEY, None)
    if normalizer_name:
        services[TEXT_NORMALIZER_KEY] = create_text_label_normalizer(
            normalizer_name,
            params=normalizer_params,
            llm_client=llm_client,
            llm_model=model,
        )

    return SPACE_TYPE_CLASSIFIERS.create(
        algorithm or resolved.classifier_algorithm,
        params=merged,
        services=services,
    )


def create_text_label_normalizer(
    algorithm: str | None = None,
    params: Mapping[str, Any] | None = None,
    *,
    llm_client: Any = None,
    llm_model: str | None = None,
) -> ITextLabelNormalizer:
    """创建文本归一化算法实例。"""
    return TEXT_LABEL_NORMALIZERS.create(
        algorithm,
        params=dict(params or {}),
        services={
            "llm_client": llm_client,
            "llm_model": llm_model or _default_llm_model(),
        },
    )


def available_contour_algorithms() -> list[str]:
    return CONTOUR_EXTRACTORS.names()


def available_classifier_algorithms() -> list[str]:
    return SPACE_TYPE_CLASSIFIERS.names()


def available_text_normalizers() -> list[str]:
    return TEXT_LABEL_NORMALIZERS.names()


def resolve_contour_algorithm(
    algorithm: str | None = None, config: SpatialPipelineConfig | None = None
) -> str:
    """把轮廓算法名（或别名 / ``None``）解析成注册表中的规范名。

    ``None`` 表示使用配置中的默认值；名字非法时抛
    :class:`~src.spatial.registry.UnknownAlgorithmError`。
    """
    resolved = config or SpatialPipelineConfig.from_settings()
    return CONTOUR_EXTRACTORS.resolve_name(algorithm or resolved.contour_algorithm)


def resolve_classifier_algorithm(
    algorithm: str | None = None, config: SpatialPipelineConfig | None = None
) -> str:
    """把分类算法名（或别名 / ``None``）解析成注册表中的规范名。"""
    resolved = config or SpatialPipelineConfig.from_settings()
    return SPACE_TYPE_CLASSIFIERS.resolve_name(algorithm or resolved.classifier_algorithm)


def contour_visualization_suffix(
    algorithm: str | None = None, config: SpatialPipelineConfig | None = None
) -> str:
    """该轮廓算法在可视化文件名中使用的后缀（``cdt`` / ``rgp`` / …）。

    文件名形如 ``<drawing>_<suffix>.png``，因此调用方必须按实际使用的算法
    拼路径，不能假定是 ``cdt``。
    """
    resolved = config or SpatialPipelineConfig.from_settings()
    name = resolve_contour_algorithm(algorithm, resolved)
    return str(getattr(CONTOUR_EXTRACTORS.get_class(name), "visualization_suffix", "contour"))


def spatial_algorithm_catalog(config: SpatialPipelineConfig | None = None) -> dict[str, Any]:
    """列出可用的空间算法及其默认值，供 CLI / Web UI 呈献给用户。

    每个算法条目包含 ``id``（注册表规范名，用于回传给流水线）、``name``
    （展示名）、``summary``（文档字符串首行）以及轮廓算法特有的 ``suffix``。
    """
    resolved = config or SpatialPipelineConfig.from_settings()
    contour_algorithms = _describe(CONTOUR_EXTRACTORS, with_suffix=True)
    classifier_algorithms = _describe(SPACE_TYPE_CLASSIFIERS)
    for entry in contour_algorithms:
        entry["default"] = entry["id"] == resolve_contour_algorithm(None, resolved)
    for entry in classifier_algorithms:
        entry["default"] = entry["id"] == resolve_classifier_algorithm(None, resolved)

    return {
        "contour": {
            "label": "空间轮廓提取",
            "default": resolve_contour_algorithm(None, resolved),
            "algorithms": contour_algorithms,
        },
        "classification": {
            "label": "空间类型识别",
            "default": resolve_classifier_algorithm(None, resolved),
            "algorithms": classifier_algorithms,
        },
    }


def _describe(registry: Registry, *, with_suffix: bool = False) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key in registry.names():
        cls = registry.get_class(key)
        entry: dict[str, Any] = {
            "id": key,
            "name": str(getattr(cls, "name", key)),
            "summary": _first_doc_line(cls),
        }
        if with_suffix:
            entry["suffix"] = str(getattr(cls, "visualization_suffix", "contour"))
        entries.append(entry)
    return entries


def _first_doc_line(cls: type) -> str:
    doc = inspect.getdoc(cls) or ""
    lines = [line.strip() for line in doc.splitlines() if line.strip()]
    return lines[0].replace("``", "").replace("`", "") if lines else ""
