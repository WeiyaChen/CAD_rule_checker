# src/spatial/registry.py
"""算法注册表。

每种任务维护一张按名称索引的算法表，:mod:`src.spatial.factory` 依据配置中的
``algorithm`` 字段创建对应实例。
"""

from __future__ import annotations

import inspect
from typing import Any, Generic, Iterable, TypeVar

T = TypeVar("T")


class UnknownAlgorithmError(KeyError):
    """配置中引用了未注册的算法名。"""


class Registry(Generic[T]):
    """名称为键的算法注册表。"""

    def __init__(self, kind: str):
        self.kind = kind
        self._classes: dict[str, type[T]] = {}
        self._aliases: dict[str, str] = {}

    # ---------------------------------------------------------------- register
    def register(self, name: str, cls: type[T] | None = None, *, aliases: Iterable[str] = ()):
        """注册算法类。

        既可以作为装饰器使用（``@REGISTRY.register("CDT")``），
        也可以直接调用（``REGISTRY.register("CDT", CDTContourExtractor)``）。
        """
        if cls is None:
            def decorator(inner: type[T]) -> type[T]:
                self.register(name, inner, aliases=aliases)
                return inner

            return decorator

        key = self._normalize(name)
        self._classes[key] = cls
        for alias in aliases:
            self._aliases[self._normalize(alias)] = key
        return cls

    # ------------------------------------------------------------------- query
    def names(self) -> list[str]:
        """返回所有已注册的算法名（不含别名），保持注册顺序。"""
        return list(self._classes.keys())

    def available(self) -> dict[str, type[T]]:
        return dict(self._classes)

    def resolve_name(self, name: str | None) -> str:
        if name is None:
            if len(self._classes) == 1:
                return next(iter(self._classes))
            raise UnknownAlgorithmError(
                f"No {self.kind} algorithm specified. Available: {self.names()}"
            )
        key = self._normalize(name)
        if key in self._classes:
            return key
        if key in self._aliases:
            return self._aliases[key]
        raise UnknownAlgorithmError(
            f"Unknown {self.kind} algorithm '{name}'. Available: {self._aliases_names()}"
        )

    def get_class(self, name: str | None = None) -> type[T]:
        return self._classes[self.resolve_name(name)]

    # ------------------------------------------------------------------- build
    def create(
        self,
        name: str | None = None,
        *,
        params: dict[str, Any] | None = None,
        services: dict[str, Any] | None = None,
    ) -> T:
        """按名称实例化算法。

        Args:
            name: 注册名（或别名）。
            params: 来自配置的算法参数。若目标构造函数未声明 ``**kwargs``，
                出现未知键会直接报错，避免配置写错后被静默忽略。
            services: 由流水线注入的运行时依赖（如 LLM 客户端）。目标构造函数
                未声明时会被忽略，因为这些依赖对所有同类算法并不通用。
        """
        cls = self.get_class(name)
        params = dict(params or {})
        services = dict(services or {})

        signature = inspect.signature(cls.__init__)
        parameters = signature.parameters
        accepts_var_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()
        )

        if accepts_var_kwargs:
            kwargs = {**params, **services}
        else:
            unknown = sorted(set(params) - set(parameters))
            if unknown:
                raise TypeError(
                    f"{self.kind} algorithm '{self.resolve_name(name)}' does not accept "
                    f"parameter(s): {', '.join(unknown)}"
                )
            kwargs = {**params}
            for key, value in services.items():
                if key in parameters:
                    kwargs[key] = value

        return cls(**kwargs)

    # ------------------------------------------------------------------ helper
    def _aliases_names(self) -> list[str]:
        return sorted(set(self._classes) | set(self._aliases))

    @staticmethod
    def _normalize(name: str) -> str:
        return str(name).strip().upper()


#: 空间轮廓提取算法。``IContourExtractor`` -> :class:`~src.spatial.contracts.ISpatialContourExtractor`
CONTOUR_EXTRACTORS: Registry = Registry("contour extractor")

#: 空间类型识别算法。``ISpaceTypeClassifier`` -> :class:`~src.spatial.contracts.ISpaceTypeClassifier`
SPACE_TYPE_CLASSIFIERS: Registry = Registry("space type classifier")

#: 文本归一化算法。
TEXT_LABEL_NORMALIZERS: Registry = Registry("text label normalizer")
