# src/spatial/__init__.py
"""空间语义处理的可插拔层。

本包把原先散落在流水线中的两项任务抽成独立、可替换的算法：

* **空间轮廓提取**（:class:`~src.spatial.contracts.ISpatialContourExtractor`）
* **空间类型识别**（:class:`~src.spatial.contracts.ISpaceTypeClassifier`）

算法之间通过 :mod:`src.spatial.domain` 中的领域对象通信，与 JSON-LD / 知识图谱
解耦；具体实现注册到 :mod:`src.spatial.registry`，由 :mod:`src.spatial.factory`
按 ``settings.yaml`` 中的配置创建：:

    from src.spatial import create_contour_extractor, create_space_type_classifier

    extractor = create_contour_extractor()            # 默认 CDT
    classifier = create_space_type_classifier()       # 默认 LLMMultiStage

新增同类算法只需实现接口并注册，无需改动流水线代码。

包内布局（与空间流水线有关的东西都集中在这里，不再散落在 ``topology`` / ``utils``）::

    spatial/
    ├── contracts.py        # 接口定义
    ├── domain.py           # 算法之间传递的领域对象
    ├── registry.py         # 注册表（名字 / 别名）
    ├── factory.py          # 按配置创建算法实例
    ├── config.py           # settings.yaml 中 spatial 段的解析
    ├── primitives.py       # 边界图元准备（所有轮廓算法共用的输入）
    ├── visualization.py    # 轮廓提取结果绘图（与算法无关）
    ├── contours/           # 空间轮廓提取算法
    └── classifiers/        # 空间类型识别算法
"""

from . import contours as _contours  # noqa: F401  触发轮廓算法注册
from . import classifiers as _classifiers  # noqa: F401  触发分类算法注册
from .config import (
    DEFAULT_CLASSIFIER_ALGORITHM,
    DEFAULT_CLASSIFIER_PARAMS,
    DEFAULT_CONTOUR_ALGORITHM,
    DEFAULT_CONTOUR_PARAMS,
    SpatialPipelineConfig,
)
from .contracts import (
    ISpaceTypeClassifier,
    ISpatialContourExtractor,
    ITextLabelNormalizer,
)
from .domain import (
    SOURCE_LLM_INFERENCE,
    SOURCE_TEXT_MATCH,
    UNKNOWN_LABEL,
    SpatialComponent,
    SpatialContour,
    SpaceTypePrediction,
    TextAnnotation,
    contours_to_legacy_dicts,
)
from .factory import (
    available_classifier_algorithms,
    available_contour_algorithms,
    available_text_normalizers,
    contour_visualization_suffix,
    create_contour_extractor,
    create_space_type_classifier,
    create_text_label_normalizer,
    resolve_classifier_algorithm,
    resolve_contour_algorithm,
    spatial_algorithm_catalog,
)
from .registry import (
    CONTOUR_EXTRACTORS,
    SPACE_TYPE_CLASSIFIERS,
    TEXT_LABEL_NORMALIZERS,
    Registry,
    UnknownAlgorithmError,
)

__all__ = [
    "CONTOUR_EXTRACTORS",
    "DEFAULT_CLASSIFIER_ALGORITHM",
    "DEFAULT_CLASSIFIER_PARAMS",
    "DEFAULT_CONTOUR_ALGORITHM",
    "DEFAULT_CONTOUR_PARAMS",
    "ISpaceTypeClassifier",
    "ISpatialContourExtractor",
    "ITextLabelNormalizer",
    "Registry",
    "SOURCE_LLM_INFERENCE",
    "SOURCE_TEXT_MATCH",
    "SPACE_TYPE_CLASSIFIERS",
    "SpatialComponent",
    "SpatialContour",
    "SpatialPipelineConfig",
    "SpaceTypePrediction",
    "TEXT_LABEL_NORMALIZERS",
    "TextAnnotation",
    "UNKNOWN_LABEL",
    "UnknownAlgorithmError",
    "available_classifier_algorithms",
    "available_contour_algorithms",
    "available_text_normalizers",
    "contour_visualization_suffix",
    "contours_to_legacy_dicts",
    "create_contour_extractor",
    "create_space_type_classifier",
    "create_text_label_normalizer",
    "resolve_classifier_algorithm",
    "resolve_contour_algorithm",
    "spatial_algorithm_catalog",
]
