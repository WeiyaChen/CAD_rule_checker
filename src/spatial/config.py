# src/spatial/config.py
"""空间算法的运行时配置。

配置来源是 ``src/config/settings.yaml`` 的 ``spatial`` 段；此处定义的默认值与
重构前散落在算法内部的硬编码阈值完全一致，因此即使 YAML 中缺少该段，行为
也与历史版本保持相同。

YAML 结构::

    spatial:
      contour:
        algorithm: "CDT"
        params:                 # 所有轮廓算法共用的参数
          min_area_mm2: 2000000
          ...
        algorithm_params:       # 按算法名分组的专属参数，只在该算法被选中时生效
          RGP:
            snap_tol_mm: 10.0
      classification:
        algorithm: "LLMMultiStage"
        params:
          text_normalizer: "LLM"
          ...

``params`` 里的键必须被当前算法的构造函数接受（否则 :class:`~src.spatial.registry.Registry`
会报错）。当多个算法共用同一个 ``spatial`` 段时，把某个算法独有的参数放进
``algorithm_params``，这样在算法之间来回切换都不会因为"多出未知参数"而失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .registry import (
    CONTOUR_EXTRACTORS,
    SPACE_TYPE_CLASSIFIERS,
    Registry,
    UnknownAlgorithmError,
)

#: ``CDTContourExtractor`` 的默认参数（等同于重构前的硬编码阈值）。
DEFAULT_CONTOUR_ALGORITHM = "CDT"
DEFAULT_CONTOUR_PARAMS: dict[str, Any] = {
    # 防线 1：绝对面积下限，剔除微小碎片（mm²）
    "min_area_mm2": 2000000.0,
    # 防线 2：形态学负缓冲半径（mm），用于剔除"工"字形墙缝
    "erode_mm": 250.0,
    # 防线 3：最小旋转外接矩形短边（mm）
    "min_width_mm": 600.0,
    # 防线 4：紧凑度 / 实心率下限
    "min_compactness": 0.08,
    "min_solidity": 0.25,
    # 门窗虚拟封口边判定
    "virtual_blocker_dist_tol_mm": 300.0,
    "virtual_blocker_max_len_mm": 3500.0,
    "virtual_blocker_angle_tol_deg": 0.0,
}

#: ``LLMMultiStageClassifier`` 的默认参数。
DEFAULT_CLASSIFIER_ALGORITHM = "LLMMultiStage"
DEFAULT_CLASSIFIER_PARAMS: dict[str, Any] = {
    # 文字锚点落在轮廓外时允许的容差（mm）。0 表示只接受严格包含，
    # 与重构前的行为一致；调大后可吸收 OCR 锚点偏移。
    "match_tolerance_mm": 0.0,
    # 低于该置信度的预测会被丢弃。
    "min_confidence": 0.5,
    # 可选：显式指定文本归一化算法（见 TEXT_LABEL_NORMALIZERS）。
    # 默认留空，让各分类算法使用自己的缺省值——``LLMMultiStage`` 用 ``LLM``，
    # ``TextMatching`` 用 ``Dictionary``。若要离线运行大模型算法，可设为
    # ``Dictionary`` 以避免走大模型兜底数据。
    # "text_normalizer": "Dictionary",
    # 传给文本归一化算法的参数，例如 {"mapping": {...}} 或 {"fallback_mapping": {...}}。
    # "text_normalizer_params": {},
}


@dataclass(frozen=True)
class SpatialPipelineConfig:
    """空间轮廓提取 + 空间类型识别的整体配置。"""

    contour_algorithm: str = DEFAULT_CONTOUR_ALGORITHM
    contour_params: Mapping[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_CONTOUR_PARAMS)
    )
    classifier_algorithm: str = DEFAULT_CLASSIFIER_ALGORITHM
    classifier_params: Mapping[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_CLASSIFIER_PARAMS)
    )
    #: 按算法名分组的轮廓参数（仅选中该算法时合并进 ``contour_params``）。
    contour_algorithm_params: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    #: 按算法名分组的分类参数（仅选中该算法时合并进 ``classifier_params``）。
    classifier_algorithm_params: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )

    @classmethod
    def from_settings(cls, settings_obj=None) -> "SpatialPipelineConfig":
        """从 :class:`src.config.config.Settings` 读取配置。"""
        if settings_obj is None:
            from src.config.config import settings as settings_obj

        contour_algorithm = settings_obj.spatial_contour_algorithm or DEFAULT_CONTOUR_ALGORITHM
        contour_algorithm_params = _as_mapping(settings_obj.spatial_contour_algorithm_params)
        contour_params = dict(DEFAULT_CONTOUR_PARAMS)
        contour_params.update(_as_mapping(settings_obj.spatial_contour_params))
        contour_params.update(
            _algorithm_overrides(contour_algorithm_params, contour_algorithm, CONTOUR_EXTRACTORS)
        )

        classifier_algorithm = (
            settings_obj.spatial_classifier_algorithm or DEFAULT_CLASSIFIER_ALGORITHM
        )
        classifier_algorithm_params = _as_mapping(
            settings_obj.spatial_classifier_algorithm_params
        )
        classifier_params = dict(DEFAULT_CLASSIFIER_PARAMS)
        classifier_params.update(_as_mapping(settings_obj.spatial_classifier_params))
        classifier_params.update(
            _algorithm_overrides(
                classifier_algorithm_params, classifier_algorithm, SPACE_TYPE_CLASSIFIERS
            )
        )

        return cls(
            contour_algorithm=contour_algorithm,
            contour_params=contour_params,
            classifier_algorithm=classifier_algorithm,
            classifier_params=classifier_params,
            contour_algorithm_params=contour_algorithm_params,
            classifier_algorithm_params=classifier_algorithm_params,
        )


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _algorithm_overrides(
    overrides: Mapping[str, Any],
    algorithm: str,
    registry: Registry | None = None,
) -> dict[str, Any]:
    """从 ``algorithm_params`` 中取出当前算法对应的那一组参数。

    键名按注册名匹配（大小写不敏感），并顺带解析别名，因此
    ``algorithm: POLYGONIZE`` 也能命中 ``algorithm_params.RGP``。
    """
    if not overrides or not algorithm:
        return {}

    candidates = {str(algorithm).strip().upper()}
    if registry is not None:
        try:
            candidates.add(registry.resolve_name(algorithm))
        except UnknownAlgorithmError:
            pass  # 未注册的算法名交由 registry.create() 报错

    for name, values in overrides.items():
        if str(name).strip().upper() in candidates:
            return _as_mapping(values)
    return {}
