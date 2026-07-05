def get_label_list():
    label_list = [
        "single door",
        "double door",
        "sliding door",
        "folding door",
        "revolving door",
        "rolling door",
        "window",
        "bay window",
        "blind window",
        "opening symbol",
        "sofa",
        "bed",
        "chair",
        "table",
        "TV cabinet",
        "Wardrobe",
        "cabinet",
        "gas stove",
        "sink",
        "refrigerator",
        "airconditioner",
        "bath",
        "bath tub",
        "washing machine",
        "urinal",
        "squat toilet",
        "toilet",
        "stairs",
        "elevator",
        "escalator",
        "row chairs",
        "parking spot",
        "wall",
        "curtain wall",
        "railing"
    ]
    return label_list

def get_wall():
    # 1. 墙体/边界类：定义空间的封闭线或边缘
    boundary_labels = {
        "wall",
        "curtain wall",
        "railing",
        "window",
        "bay window",
        "blind window"
    }

    return boundary_labels


def get_door():
    # 2. 洞口类：嵌入在墙体上的元素
    opening_labels = {
        "single door",
        "double door",
        "sliding door",
        "folding door",
        "revolving door",
        "rolling door",
        "opening symbol"
    }
    return opening_labels

def get_window():
    window_labels = {
        "window",
        "bay window",
        "blind window"
    }
    return window_labels


def get_color():
    SVG_CATEGORIES = [
        # 1-6 doors
        {"color": [224, 62, 155], "isthing": 1, "id": 1, "name": "single door"},
        {"color": [157, 34, 101], "isthing": 1, "id": 2, "name": "double door"},
        {"color": [232, 116, 91], "isthing": 1, "id": 3, "name": "sliding door"},
        {"color": [101, 54, 72], "isthing": 1, "id": 4, "name": "folding door"},
        {"color": [172, 107, 133], "isthing": 1, "id": 5, "name": "revolving door"},
        {"color": [142, 76, 101], "isthing": 1, "id": 6, "name": "rolling door"},
        # 7-10 window
        {"color": [96, 78, 245], "isthing": 1, "id": 7, "name": "window"},
        {"color": [26, 2, 219], "isthing": 1, "id": 8, "name": "bay window"},
        {"color": [63, 140, 221], "isthing": 1, "id": 9, "name": "blind window"},
        {"color": [233, 59, 217], "isthing": 1, "id": 10, "name": "opening symbol"},
        # 11-27: furniture
        {"color": [122, 181, 145], "isthing": 1, "id": 11, "name": "sofa"},
        {"color": [94, 150, 113], "isthing": 1, "id": 12, "name": "bed"},
        {"color": [66, 107, 81], "isthing": 1, "id": 13, "name": "chair"},
        {"color": [123, 181, 114], "isthing": 1, "id": 14, "name": "table"},
        {"color": [94, 150, 83], "isthing": 1, "id": 15, "name": "TV cabinet"},
        {"color": [66, 107, 59], "isthing": 1, "id": 16, "name": "Wardrobe"},
        {"color": [145, 182, 112], "isthing": 1, "id": 17, "name": "cabinet"},
        {"color": [152, 147, 200], "isthing": 1, "id": 18, "name": "gas stove"},
        {"color": [113, 151, 82], "isthing": 1, "id": 19, "name": "sink"},
        {"color": [112, 103, 178], "isthing": 1, "id": 20, "name": "refrigerator"},
        {"color": [81, 107, 58], "isthing": 1, "id": 21, "name": "airconditioner"},
        {"color": [172, 183, 113], "isthing": 1, "id": 22, "name": "bath"},
        {"color": [141, 152, 83], "isthing": 1, "id": 23, "name": "bath tub"},
        {"color": [80, 72, 147], "isthing": 1, "id": 24, "name": "washing machine"},
        {"color": [100, 108, 59], "isthing": 1, "id": 25, "name": "squat toilet"},
        {"color": [182, 170, 112], "isthing": 1, "id": 26, "name": "urinal"},
        {"color": [238, 124, 162], "isthing": 1, "id": 27, "name": "toilet"},
        # 28:stairs
        {"color": [247, 206, 75], "isthing": 1, "id": 28, "name": "stairs"},
        # 29-30: equipment
        {"color": [237, 112, 45], "isthing": 1, "id": 29, "name": "elevator"},
        {"color": [233, 59, 46], "isthing": 1, "id": 30, "name": "escalator"},

        # 31-35: uncountable
        {"color": [172, 107, 151], "isthing": 0, "id": 31, "name": "row chairs"},
        {"color": [102, 67, 62], "isthing": 0, "id": 32, "name": "parking spot"},
        {"color": [167, 92, 32], "isthing": 0, "id": 33, "name": "wall"},
        {"color": [121, 104, 178], "isthing": 0, "id": 34, "name": "curtain wall"},
        {"color": [64, 52, 105], "isthing": 0, "id": 35, "name": "railing"},
        {"color": [0, 0, 0], "isthing": 0, "id": 36, "name": "bg"},
    ]
    return SVG_CATEGORIES