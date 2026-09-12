# src/topology/builder.py
"""拓扑构建编排：图元 → 房间轮廓 → BOT 拓扑图。

轮廓提取算法由 :mod:`src.spatial` 提供（可插拔），边界图元准备在
:mod:`src.spatial.primitives`，构件聚合在 :mod:`src.topology.components`，
本模块只负责把这些步骤编排起来并落盘 JSON-LD 与可视化。
"""

import os

from shapely import Polygon

from .bot_builder import BotGraphGenerator
from .components import process_compound_instances
from ..spatial import (
    SpatialComponent,
    TextAnnotation,
    contours_to_legacy_dicts,
    create_contour_extractor,
)
from ..spatial.primitives import clean_lines
from ..spatial.visualization import plot_floor_plan
from ..utils.graph_viz import BotGraphVisualizer
from src.config.config import settings
from src.config.labels import get_wall, get_window, get_door


class TopologyBuilder:
    def __init__(self, contour_extractor=None, contour_algorithm=None, contour_params=None):
        """
        Args:
            contour_extractor: 已实例化的空间轮廓提取算法。传入后由调用方管理其生命周期，
                并会在每次 ``build()`` 中复用；``None`` 时按算法名在每次 ``build()`` 中新建。
            contour_algorithm: 轮廓提取算法注册名，``None`` 时使用配置文件中的默认值。
            contour_params: 覆盖配置文件中的算法参数。
        """
        self._contour_extractor = contour_extractor
        self._contour_algorithm = contour_algorithm
        self._contour_params = contour_params

    def _create_contour_extractor(self, contour_algorithm=None, contour_params=None):
        """解析本次构建要使用的轮廓提取算法实例。

        未注入实例时每次都新建一个，避免上一次构建残留的网格状态影响可视化。
        """
        if self._contour_extractor is not None:
            return self._contour_extractor
        return create_contour_extractor(
            contour_algorithm or self._contour_algorithm,
            contour_params if contour_params is not None else self._contour_params,
        )

    def build(self, raw_elements, json_output_path, contour_algorithm=None, contour_params=None):
        """
        Main pipeline: Elements -> FloorPlan Object
        """
        walls = [e for e in raw_elements if e['type'] in get_wall()]  # 找到边界图元图元
        clean_walls = clean_lines(walls)

        # 提取并合并门
        raw_doors = [e for e in raw_elements if e['type'] in get_door()]
        door_objs = process_compound_instances(raw_doors, target_category="Door")

        # 提取合并窗
        raw_windows = [e for e in raw_elements if e['type'] in get_window()]
        window_objs = process_compound_instances(raw_windows, target_category="Window")

        # 提取合并家具
        raw_furn = [
            e for e in raw_elements
            if e['type'] not in get_wall()
               and e['type'] not in get_door()
               and e['type'] != "text"
        ]
        fun_objs = process_compound_instances(raw_furn, target_category="FunctionalElement")

        # patches提取
        # 正确写法 (转为 Shapely 对象):
        door_patches = []
        for d in door_objs:
            if d.geometry:
                try:
                    door_patches.append(Polygon(d.geometry))
                except Exception as e:
                    print(f"Invalid geometry for Door {d.uid}: {e}")

        window_patches = []
        for w in window_objs:
            if w.geometry:
                try:
                    window_patches.append(Polygon(w.geometry))
                except Exception as e:
                    print(f"Invalid geometry for Window {w.uid}: {e}")

        # 生成房间标签列表
        rooms = [e for e in raw_elements if e['type'] == 'text']
        text_annotations = []
        for room in rooms:
            content = room.get('text')
            cord = room.get('coords')
            text_annotations.append(TextAnnotation(raw_text=content, point=(cord[0], cord[1])))

        comps = door_objs + window_objs + fun_objs
        components = [
            SpatialComponent(uid=c.uid, category=c.category, specific_type=c.specific_type)
            for c in comps
        ]

        # 构建房间轮廓（具体算法由配置决定，默认 CDT）
        extractor = self._create_contour_extractor(contour_algorithm, contour_params)
        room_contours = extractor.extract(
            walls=clean_walls,
            doors=door_patches,
            windows=window_patches,
            texts=text_annotations,
            components=components,
        )
        room_results = contours_to_legacy_dicts(room_contours)

        # 调用可视化
        save_dir = str(settings.viz_dir)
        suffix = getattr(extractor, "visualization_suffix", "contour")
        filename = os.path.basename(json_output_path).replace("_raw.jsonld", f"_{suffix}.png")
        plot_floor_plan(extractor, room_results, save_dir, filename)

        # bot构建
        generator = BotGraphGenerator(room_results, comps)
        json_output = generator.generate()
        # 实例化可视化工具
        viz = BotGraphVisualizer(json_output)
        viz.save_json(json_output_path)
