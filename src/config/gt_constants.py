"""
Ground Truth (GT) construction constants.

Centralized configuration used by `ground_truth_creator.py` for building the
BIM knowledge graph ground truth from annotated DXF files: layer-to-semantic
mappings, door/functional-element layers, JSON-LD context, semantic seed sets, and
visualization color maps.
"""

# =====================================================================
# Layer-to-semantic mapping and element layers
# =====================================================================
# Bilingual standard layer names mapped to semantic types (Chinese/English)
LAYER_SEMANTIC_MAP = {
    "GT_BEDROOM": "Bedroom", "GT_卧室": "Bedroom",
    "GT_LIVINGROOM": "LivingRoom", "GT_客厅": "LivingRoom",
    "GT_KITCHEN": "Kitchen", "GT_厨房": "Kitchen",
    "GT_BATHROOM": "Bathroom", "GT_卫生间": "Bathroom",
    "GT_BALCONY": "Balcony", "GT_阳台": "Balcony",
    "GT_CORRIDOR": "Corridor", "GT_过道": "Corridor",
    "GT_ENTRANCE": "Entrance", "GT_玄关": "Entrance",
    "GT_GARDEN": "Garden", "GT_花园": "Garden",
    "GT_DININGROOM": "DiningRoom", "GT_餐厅": "DiningRoom",
    "GT_ELEVATORSHAFT": "ElevatorShaft", "GT_电梯": "ElevatorShaft",
    "GT_STORAGEROOM": "StorageRoom", "GT_储藏间": "StorageRoom",
    "GT_STAIRWELL": "Stairwell", "GT_楼梯": "Stairwell",
    "GT_CLOAKROOM": "Cloakroom", "GT_衣帽间": "Cloakroom",
    "GT_STUDYROOM": "StudyRoom", "GT_书房": "StudyRoom",
    "GT_SUNROOM": "SunRoom", "GT_阳光房": "SunRoom",
    "GT_WATERROOM": "WaterRoom", "GT_水机房": "WaterRoom",
    "GT_ELECTRICALROOM": "ElectricalRoom", "GT_电机房": "ElectricalRoom",
    "GT_VENTILATIONROOM": "VentilationRoom", "GT_风机房": "VentilationRoom"
}

# Layers representing doors
DOOR_LAYERS = ["GT_DOOR", "GT_门"]

# Internal functional-element layer mapping to BEO element types
FUNCTIONAL_ELEMENT_MAP = {
    "GT_SINK": "beo:Sink", "GT_水槽": "beo:Sink",
    "GT_BATHTUB": "beo:Bathtub", "GT_浴缸": "beo:Bathtub",
    "GT_BATH": "beo:Bath", "GT_洗浴区": "beo:Bath",
    "GT_GASSTOVE": "beo:GasStove", "GT_燃气灶": "beo:GasStove",
    "GT_TOILET": "beo:Toilet", "GT_便器": "beo:Toilet"
}

# =====================================================================
# JSON-LD context
# =====================================================================
JSONLD_CONTEXT = {
    "bot": "https://w3id.org/bot#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "inst": "http://mythesis.org/instance/",
    "props": "http://mythesis.org/props/",
    "beo": "https://pi.pauwel.be/voc/buildingelement#",
    "bldg": "http://mythesis.org/bldg/",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "xsd": "http://www.w3.org/2001/XMLSchema#"
}

# =====================================================================
# Semantic classification seed sets
# =====================================================================
# Rooms treated as public/exterior core spaces
PUBLIC_SEEDS = {"ElevatorShaft", "Stairwell", "WaterRoom", "ElectricalRoom", "VentilationRoom", "EquipmentRoom"}

# Rooms treated as private residential spaces
PRIVATE_SEEDS = {"Bedroom", "LivingRoom", "Kitchen", "Bathroom", "DiningRoom", "Cloakroom", "StudyRoom", "Balcony",
                 "Entrance"}

# Room types that block suite grouping during BFS
PUBLIC_BLOCKERS = {"ElevatorShaft", "Stairwell", "WaterRoom", "ElectricalRoom", "VentilationRoom", "EquipmentRoom",
                   "PublicCorridor", "Unknown"}

# =====================================================================
# Visualization color map (room semantic -> hex color)
# =====================================================================
ROOM_COLOR_MAP = {
    "Bedroom": "#AEC6CF",  # light blue
    "LivingRoom": "#FFDAC1",  # light peach
    "Kitchen": "#FFB7B2",  # light red
    "Bathroom": "#B19CD9",  # light purple
    "Balcony": "#CFCFC4",  # light gray
    "Corridor": "#FDFD96",  # light yellow
    "Entrance": "#FFB7C5",  # light pink
    "DiningRoom": "#E2F0CB",  # light cyan
    "PublicCorridor": "#D3D3D3",  # medium gray (public area)
    "StudyRoom": "#C5E3BF",  # light green
    "StorageRoom": "#E0C9A6",  # light brown
    "Unknown": "#F5F5F5"  # off-white (unknown)
}
