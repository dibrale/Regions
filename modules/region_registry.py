import json
import logging
import pathlib

from dynamic_rag import DynamicRAGSystem
from llamacpp_api import LLMLink
from region_types import *
from dataclasses import dataclass
from typing import List

from functools import partial
import inspect


@dataclass
class RegionEntry:
    """Configuration and state container for region instances in a distributed system.

    Represents a serialized blueprint for a region (a specialized component in a multi-agent system).
    Contains both metadata (name, type, task) and runtime dependencies (RAG systems, LLMs, connections).
    Used to:
    - Persist region configurations
    - Recreate regions from stored state
    - Manage inter-region relationships

    Attributes:
        name (str): Unique identifier for the region. Default: None
        type (str): Fully qualified class name of the region implementation. Default: None
        task (str): Primary objective/functionality description of the region. Default: None
        connections (list[str]): Names of regions this region interacts with. Default: None
        rag (DynamicRAGSystem): Optional retrieval-augmented generation system for knowledge access. Default: None
        llm (LLMLink): Optional language model interface for generating responses. Default: None
        region (BaseRegion): Live instance of the region (populated when active). Default: None
        reply_with_actors (bool): Whether responses should include actor references. Default: None

    Example:
        >>> entry = RegionEntry(name="customer_support", type="regions.SupportRegion")
        >>> entry.from_region(support_region_instance)
        >>> recreated_region = entry.make_region()
    """
    name: str = None
    type: str = None
    task: str = None
    connections: list[str] = None
    rag: DynamicRAGSystem = None
    llm: LLMLink = None
    region: BaseRegion = None
    reply_with_actors: bool = None

    def __repr__(self):
        """Return debug-friendly representation showing region name.

        Returns:
            str: Formatted string like '<RegionEntry name=...>' for inspection.
        """
        return f"<RegionEntry name={self.name}>"

    def __str__(self):
        """Return human-readable name of the region.

        Returns:
            str: Region name (e.g., 'customer_support').
        """
        return f"{self.name}"

    def from_region(self, region: BaseRegion):
        """Populate entry attributes from a live region instance.

        Copies critical metadata and optional dependencies from a BaseRegion object.
        Handles optional attributes (rag, llm, reply_with_actors) safely via hasattr checks.

        Args:
            region (BaseRegion): Source region instance to serialize

        Side Effects:
            Sets all attributes on self:
            - name, type (from class name), task, connections
            - rag (if present on region)
            - llm (if present on region)
            - reply_with_actors (if present on region)
            - region (direct reference to source object)

        Example:
            >>> entry = RegionEntry()
            >>> entry.from_region(customer_region)
            >>> assert entry.name == "customer_region"
        """
        self.name = region.name
        self.type = str_from_class(region.__class__)

        # Alternate code (no checks for dictionary presence)
        # self.type = type(region).__name__

        self.task = region.task
        self.connections = region.connections
        if hasattr(region, "rag"):
            self.rag = region.rag
        if hasattr(region, "llm"):
            self.llm = region.llm
        if hasattr(region, "reply_with_actors"):
            self.reply_with_actors = region.reply_with_actors
        self.region = region

    def make_region(self):
        """Instantiate a region from stored configuration.

        Recreates a region object using the entry's metadata and dependencies.
        Uses partial application to build constructor arguments incrementally.

        Behavior:
            - If region already exists: Logs recreation attempt
            - On success: Populates self.region and logs creation
            - On failure: Logs error with exception details

        Side Effects:
            Sets self.region to new instance (or retains old instance on failure)

        Returns:
            BaseRegion: Created region instance (also stored in self.region)

        Raises:
            Exception: If region construction fails (logged internally)

        Example:
            >>> entry = RegionEntry(name="sales", type="regions.SalesRegion")
            >>> region = entry.make_region()
            >>> assert isinstance(region, BaseRegion)
        """
        if self.region:
            logging.info(f"Remaking '{self.name}' {self.type}")

        f = partial(
            class_from_str(self.type),
            name=self.name,
            task=self.task,
            connections={}
        )

        if self.rag:
            f = partial(f, rag=self.rag)
        if self.llm:
            f = partial(f, llm=self.llm)
        if self.reply_with_actors:
            f = partial(f, reply_with_actors=self.reply_with_actors)

        try:
            self.region = f()
            logging.info(f"Created '{self.name}' {self.type} from entry")
        except Exception as e:
            logging.error(f"Exception while making '{self.name}' {self.type}: {e}")
        return self.region

    @classmethod
    def load_list(cls, path: str) -> List["RegionEntry"]:
        """Load and validate region configuration from a JSON file.

                Reads a JSON file containing serialized region entries and converts them into
                RegionEntry objects. Enforces critical validation that all region names are unique
                to prevent routing conflicts in the distributed system.

                The JSON file must contain a list of dictionaries where each dictionary has keys
                corresponding to RegionEntry attributes (name, type, task, etc.). Missing optional
                fields will be initialized with None values per the dataclass defaults.

                Args:
                    path (str): File path to JSON configuration (supports POSIX-style paths)

                Returns:
                    List[RegionEntry]: Validated list of region entry objects

                Raises:
                    ValueError: If duplicate region names are detected in the source file
                    FileNotFoundError: If the specified path doesn't exist
                    JSONDecodeError: If the file contains invalid JSON

                Validation:
                    Performs critical uniqueness check on region names:
                    - Compares total entries against unique names (len vs set)
                    - Fails immediately on duplicates to prevent system instability

                Example:
                    >>> entries = RegionEntry.load_list("config/regions.json")
                    >>> print(f"Loaded {len(entries)} unique regions")
                    >>> assert all(e.region is None for e in entries)  # Regions not yet instantiated

                Note:
                    This method only deserializes configuration metadata - actual region instances
                    must be created separately via RegionEntry.make_region(). The returned entries
                    contain no live region objects (region attribute remains None).
                """
        posix_path = pathlib.PurePosixPath(path)

        with open(str(posix_path)) as f:
            raw_list = json.load(f)     # [{"name": ..., "type": ..., ...}, ...]
            name_roll = []
            for entry in raw_list: name_roll.append(entry['name'])
            if len(name_roll) != len(set(name_roll)):
                raise ValueError(f"Duplicate region names in list from '{posix_path.name}'")
        return [cls(**item) for item in raw_list]

class RegionRegistry:
    def __init__(self,
                 region_list: List[RegionEntry] = None,
                 default_rag: DynamicRAGSystem = DynamicRAGSystem(),
                 default_llm: LLMLink = LLMLink(),
    ):
        if not region_list:
            self.regions: List[RegionEntry] = []
            self.names = []
        else:
            self.regions = region_list
            self._update_names()
        self.live = False
        self.default_rag = default_rag
        self.default_llm = default_llm

    def __len__(self):
        return len(self.regions)

    def __getitem__(self, item: str):
        return self.regions[self.names.index(item)].region

    def __setitem__(self, key: str, value: BaseRegion):
        entry = RegionEntry()
        entry.from_region(value)
        entry.name = key
        entry.region.name = key
        self.register(entry)
        self.update(entry)

    def __iter__(self):
        return iter(self.regions)

    def _update_names(self):
        self.names = []
        for entry in self.regions: self.names.append(entry.name)

    def register(self, region: RegionEntry) -> bool:
        if region.name not in self.names:
            self.names.append(region.name)
            self.regions.append(region)
            logging.info(f"Region '{region.name}' registered")
            return True
        else:
            logging.warning(f"Region '{region.name}' already registered")
            return False

    def update(self, region: RegionEntry):
        if region.name not in self.names:
            logging.warning(f"Region '{region.name}' not found in registry")
            return False
        else:
            self.regions[self.names.index(region.name)].region = region
            logging.info(f"Region '{region.name}' updated")
            return True

    def deregister(self, name: str) -> bool:
        removed = False
        for region in self.regions:
            if region.name == name:
                self.regions.remove(region)
                self.names.remove(name)
                removed = True
                break
        if not removed: logging.warning(f"No region '{name}' in registry")
        return removed

    def load(self, path: str) -> bool:
        posix_path = pathlib.PurePosixPath(path)

        try:
            self.regions = RegionEntry.load_list(str(posix_path))
        except FileNotFoundError:
            logging.error(f"File '{posix_path.name}' not found at '{str(posix_path.parent)}'.")
            return False
        except json.decoder.JSONDecodeError:
            logging.error(f"File '{posix_path.name}' not valid JSON.")
            return False
        except Exception as e:
            logging.error(f"Problem loading file '{posix_path.name}' from '{str(posix_path.parent)}': {e}")
            return False

        self._update_names()
        logging.info(f"Registered regions from '{posix_path.name}' at '{str(posix_path.parent)}'")
        return True

    def verify(self) -> tuple[list[str], list[str]]:
        print("Verifying registry...")
        issues = []
        warnings = []
        names_from_entries = []

        # Are there regions to verify?
        if not self.regions:
            print("No regions registered")
            return issues, warnings

        # Is there the same number of names as regions?
        logging.info(f"Found {len(self.regions)} regions and {len(self.names)} names")

        # Check they're 1:1, irrespective of order

        for entry in self.regions:
            names_from_entries.append(entry.name)

        if len(self.regions) != len(self.names):
            orphaned_regions = set(names_from_entries) - set(self.names)
            orphaned_names = set(self.names) - set(names_from_entries)
            if orphaned_regions:
                issues.append(f"Found {len(orphaned_regions)} orphaned regions: {', '.join(list(orphaned_regions))}")
            if orphaned_names:
                issues.append(f"Found {len(orphaned_names)} orphaned names: {', '.join(list(orphaned_names))}")

        # Keep verifying regardless

        # Reconcile region name of each entry with names list
        for region in self.regions:
            if region.name not in self.names:
                issues.append(f"Region '{region.name}' present, but not found in name list")
            if not region.type:
                issues.append(f"No type given for region '{region.name}'")
            else:
                try:
                    class_from_str(region.type)
                except TypeError or NameError as e:
                    issues.append(f"'{region.name}': {e}")
            if not region.task:
                issues.append(f"No task given for region '{region.name}'")
            param_string = str(inspect.signature(class_from_str(region.type)).parameters)
            if 'DynamicRAGSystem' in param_string:
                if not region.rag:
                    warnings.append(f"No RAG given for region '{region.name}' - will set default on build")
            if 'LLMLink' in param_string:
                if not region.llm:
                    warnings.append(f"No LLM given for region '{region.name}' - will set default on build")
            if region.connections:
                for connection in region.connections:
                    if not connection in self.names:
                        issues.append(f"Connection to '{connection}' specified for '{region.name}', but no such region in name list")
            else:
                warnings.append(f"No outgoing connections specified from region '{region.name}'")

        print("=== Registry Verification Result ===\n")
        if issues:
            print(f"Found {len(issues)} issues:\n")
            for issue in issues:
                logging.error(issue)
        else:
            logging.info("Verified successfully")
        if warnings:
            print(f"\n{len(warnings)} warnings: {', '.join(warnings)}\n")
            for warning in warnings:
                logging.warning(warning)
        return issues, warnings


    def build_regions(self, overwrite: bool = False, verify = True) -> bool:

        # Verify before building
        if verify:
            issues, warnings = self.verify()
        else:
            issues = None
        if issues:
            logging.error(f"Build cancelled due to verification issues. Address these before proceeding, or disable verification.")
        if not self.regions:
            logging.error("No regions registered")
            return False

        # Start build
        logging.info(f"Attempting to build {len(self.regions)} regions...")
        built = 0
        faultless = True

        for entry in self.regions:

            # Do not overwrite existing region info if overwrite disabled
            if entry.region and not overwrite:
                logging.info(f"Skipping build of region '{entry.name}'")

            else:
                # Assign default RAG and/or LLM as threatened in 'verify'
                param_string = str(inspect.signature(class_from_str(entry.type)).parameters)
                if 'DynamicRAGSystem' in param_string:
                    if not entry.rag:
                        entry.rag = self.default_rag
                        logging.info(f"RAG set to default for region '{entry.name}'")
                if 'LLMLink' in param_string:
                    if not entry.llm:
                        entry.llm = self.default_llm
                        logging.info(f"LLM set to default for region '{entry.name}'")

                # Try actually building the region
                try:
                    entry.make_region()
                    built += 1
                    logging.info(f"Successfully built region '{entry.name}'")
                except Exception as e:
                    logging.error(f"Failed to build region '{entry.name}': {e}")
                    faultless = False

        # Wrap-up and final tally
        print(f"Build done.")
        logging.info(f"Successfully built {built} out of {len(self.regions)} regions.")

        return faultless

