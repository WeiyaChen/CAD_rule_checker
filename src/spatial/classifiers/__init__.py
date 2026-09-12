# src/spatial/classifiers/__init__.py
"""空间类型识别算法集合。

导入本包即完成所有内置算法的注册，之后可通过
:data:`src.spatial.registry.SPACE_TYPE_CLASSIFIERS` 按名称创建实例。
"""

from . import matching, normalizers, prompts  # noqa: F401
from .llm_multistage import LLMMultiStageClassifier  # noqa: F401
from .text_matching import TextMatchingClassifier  # noqa: F401

__all__ = [
    "LLMMultiStageClassifier",
    "TextMatchingClassifier",
]
