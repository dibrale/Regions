from region import BaseRegion, Region, RAGRegion, MockRegion, MockRAGRegion

region_types = [
    {"name": "Region", "class": Region},
    {"name": "RAGRegion", "class": RAGRegion},
    {"name": "MockRegion", "class": MockRegion},
    {"name": "MockRAGRegion", "class": MockRAGRegion},
]

def class_from_str(class_name: str) -> type[BaseRegion]:
    for region_type in region_types:
        if region_type["name"] == class_name:
            if issubclass(region_type["class"], BaseRegion):
                return region_type["class"]
            else:
                raise TypeError(f"'{class_name}' is not a subclass of BaseRegion")
    raise NameError(f"'{class_name}' is not a defined region type")

def str_from_class(class_ref: type[BaseRegion]):
    for region_type in region_types:
        if class_ref is region_type["class"]:
            return region_type["name"]
    raise NameError(f"'{str(class_ref)}' is not associated with a string reference")

    # Alternate code:
    # return region_types[[x['name'] for x in region_types].index('RAGRegion')]["class"]