from regions.listener_region import ListenerRegion
from regions.rag_region import RAGRegion
from regions.region import Region
from regions.broadcast_region import BroadcastRegion
from tests.mock_regions import *

region_dictionary = [
    {"name": "Region", "class": Region},
    {"name": "RAGRegion", "class": RAGRegion},
    {"name": "ListenerRegion", "class": ListenerRegion},
    {"name": "BroadcastRegion", "class": BroadcastRegion},
    {"name": "MockRegion", "class": MockRegion},
    {"name": "MockRAGRegion", "class": MockRAGRegion},
    {"name": "MockListenerRegion", "class": MockListenerRegion}
]

def class_from_str(class_name: str) -> type[BaseRegion]:
    for region_type in region_dictionary:
        if region_type["name"] == class_name:
            if issubclass(region_type["class"], BaseRegion):
                return region_type["class"]
            else:
                raise TypeError(f"'{class_name}' is not a subclass of BaseRegion")
    raise NameError(f"'{class_name}' is not a defined region type")

def class_str_from_instance(instance: BaseRegion) -> str:
    for region_type in region_dictionary:
        if type(instance) is region_type["class"]:
            return region_type["name"]
    raise NameError(f"'{type(instance)}' is not associated with a string reference")

    # Alternate code:
    # return region_types[[x['name'] for x in region_types].index('RAGRegion')]["class"]