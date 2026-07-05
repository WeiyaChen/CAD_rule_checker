# src/core/spatial.py
import networkx as nx


class Room:
    """
    房间对象：包含几何轮廓、语义信息和附属构件
    这是规则审查的主要对象。
    """

    def __init__(self, name, polygon, room_type="Unknown"):
        self.name = name  # 例如 "主卧"
        self.polygon = polygon  # Shapely Polygon (净轮廓)
        self.room_type = room_type  # 例如 "Bedroom", "Kitchen"

        # 附属构件列表 (在 topology 阶段填充)
        self.windows = []
        self.doors = []

    @property
    def area(self):
        """ 返回面积 (单位转换需注意，假设输入是 mm，这里转 m2) """
        return self.polygon.area / 1e6

    @property
    def perimeter(self):
        """ 返回周长 (m) """
        return self.polygon.length / 1000.0

    @property
    def window_area(self):
        """ 计算该房间所有窗户的总面积/长度 """
        return sum([w.area for w in self.windows])

    def add_feature(self, feature):
        """ 关联窗户或门到该房间 """
        from .elements import Window, Door
        if isinstance(feature, Window):
            self.windows.append(feature)
        elif isinstance(feature, Door):
            self.doors.append(feature)


class FloorPlan:
    """
    楼层平面图对象：整个系统的容器
    包含所有房间列表和拓扑关系图
    """

    def __init__(self, name="Project_1"):
        self.name = name
        self.rooms = {}  # { "主卧": RoomObj, "厨房": RoomObj }
        self.graph = nx.Graph()  # 房间连通图
        self.raw_elements = []  # 原始图元备份

    def add_room(self, room):
        self.rooms[room.name] = room
        # 同步添加到图节点中
        self.graph.add_node(room.name, obj=room)

    def set_graph(self, graph):
        """ 注入在 Topology 层构建好的图 """
        self.graph = graph
        # 确保图节点里存了 Room 对象，方便后续检索
        for node_name in self.graph.nodes:
            if node_name in self.rooms:
                self.graph.nodes[node_name]['obj'] = self.rooms[node_name]

    def get_room(self, name):
        return self.rooms.get(name)

    def get_shortest_path(self, start_room, end_room):
        """ 路径查询接口 """
        try:
            path = nx.shortest_path(self.graph, start_room, end_room)
            return path
        except nx.NetworkXNoPath:
            return None
