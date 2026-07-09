# enricher/enricher_pipeline.py
from .acd_processor import ACDProcessor
from .geometry_enricher import GeometryEnricher
from .semantic_enricher import SemanticEnricher
from .topology_enricher import TopologyEnricher


class GraphEnrichmentPipeline:
    def __init__(self, raw_graph_dict, room_texts, llm_client=None):
        self.graph_data = raw_graph_dict
        self.room_texts = room_texts
        self.llm_client = llm_client


    def run_all(self):
        """Execute all enrichment steps in strict order."""
        print("=== Starting full-chain graph enrichment ===")

        # 1. 语义富化
        sem_engine = SemanticEnricher(self.graph_data, self.room_texts, self.llm_client)
        self.graph_data = sem_engine.execute_enrichment()

        # 2. 几何富化
        geo_engine = GeometryEnricher(self.graph_data)
        self.graph_data = geo_engine.enrich()

        # 3. 近似凸分解 (处理复合标签，切分多边形)，此处如果被注释说明在做消融实验
        acd_processor = ACDProcessor(self.graph_data)
        self.graph_data = acd_processor.process()

        # 4. 几何属性重算 (切分后的新区域面积变成 0 了，需要重新算面积和面宽)
        # geometry_enricher 需要遍历图谱，更新 props:hasArea
        geometry_enricher = GeometryEnricher(self.graph_data)
        self.graph_data = geometry_enricher.enrich()

        # 5. 门洞过道定性和套型组装
        topology_enricher = TopologyEnricher(self.graph_data)
        self.graph_data = topology_enricher.execute_enrichment()

        print("=== Full-chain enrichment complete ===")
        return self.graph_data