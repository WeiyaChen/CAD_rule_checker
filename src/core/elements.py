# src/core/elements.py
from shapely.geometry import LineString, Polygon


class BuildingElement:
    """ 所有建筑图元的基类 """

    def __init__(self, geometry, instance_id=None, properties=None):
        self.geometry = geometry  # Shapely 对象 (LineString/Polygon)
        self.instance_id = instance_id  # 实例ID (门窗有用)
        self.properties = properties or {}  # 扩展属性字典

    @property
    def bounds(self):
        return self.geometry.bounds


class Wall(BuildingElement):
    """ 墙体 """

    def __init__(self, geometry, **kwargs):
        super().__init__(geometry, **kwargs)
        # 可以在这里增加 wall_type (承重/非承重) 等属性


class Door(BuildingElement):
    """ 门 """

    def __init__(self, geometry, instance_id, **kwargs):
        super().__init__(geometry, instance_id=instance_id, **kwargs)
        self.is_emergency_exit = False  # 默认为 False，后续规则可修改


class Window(BuildingElement):
    """ 窗 """

    def __init__(self, geometry, instance_id, **kwargs):
        super().__init__(geometry, instance_id=instance_id, **kwargs)

    @property
    def area(self):
        # 这是一个简单的估算，假设高度为常数，或者如果是 Polygon 直接取面积
        if isinstance(self.geometry, Polygon):
            return self.geometry.area
        else:
            # 如果窗只是线段，返回长度 (规则层可能需要长度计算采光)
            return self.geometry.length
