# enricher/enricher_pipeline.py
import copy

from .acd_processor import ACDProcessor
from .geometry_enricher import GeometryEnricher
from .semantic_enricher import SemanticEnricher
from .topology_enricher import TopologyEnricher


class GraphEnrichmentPipeline:
    def __init__(self, raw_graph_dict, room_texts, llm_client=None, classifier=None):
        self.graph_data = raw_graph_dict
        self.room_texts = room_texts
        self.llm_client = llm_client
        # 空间类型识别算法实例；None 表示由 SemanticEnricher 按配置创建
        self.classifier = classifier
        # run_all(collect_snapshots=True) 时逐步快照写到这里，供图谱分步浏览器使用
        self.snapshots = []

    def _snapshot(self, stage):
        """记录当前阶段的图谱深拷贝（仅当 collect_snapshots=True 时有值）。"""
        self.snapshots.append({"stage": stage, "graph": copy.deepcopy(self.graph_data)})

    def run_all(self, collect_snapshots=False):
        """
        Execute all enrichment steps in strict order.

        Args:
            collect_snapshots: 若为 True，在每一步之后把当前图谱的深拷贝追加到
                ``self.snapshots``（阶段名依次为 semantic/geometry/acd/geometry2/topology），
                用于可视化每个富化阶段给知识图谱带来的变化。
        """
        print("=== Starting full-chain graph enrichment ===")
        self.snapshots = []

        # 1. 语义富化
        sem_engine = SemanticEnricher(
            self.graph_data, self.room_texts, self.llm_client, classifier=self.classifier
        )
        self.graph_data = sem_engine.execute_enrichment()
        self._snapshot("semantic")

        # 2. 几何富化
        geo_engine = GeometryEnricher(self.graph_data)
        self.graph_data = geo_engine.enrich()
        self._snapshot("geometry")

        # 3. 近似凸分解 (处理复合标签，切分多边形)，此处如果被注释说明在做消融实验
        acd_processor = ACDProcessor(self.graph_data)
        self.graph_data = acd_processor.process()
        self._snapshot("acd")

        # 4. 几何属性重算 (切分后的新区域面积变成 0 了，需要重新算面积和面宽)
        # geometry_enricher 需要遍历图谱，更新 props:hasArea
        geometry_enricher = GeometryEnricher(self.graph_data)
        self.graph_data = geometry_enricher.enrich()
        self._snapshot("geometry2")

        # 5. 门洞过道定性和套型组装
        topology_enricher = TopologyEnricher(self.graph_data)
        self.graph_data = topology_enricher.execute_enrichment()
        self._snapshot("topology")

        print("=== Full-chain enrichment complete ===")
        return self.graph_data