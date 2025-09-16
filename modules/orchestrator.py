import json
import logging
import pathlib

from utils import set_list, trim_list, check_execution_entry


class Orchestrator:
    """
    Execution planning and configuration class for region-based communication. Each registered region is assigned to at
    least one execution layer. Although regions sharing an execution layer are intended to run concurrently, subsets
    of the layer can be configured to run serially. Execution layers themselves run serially relative to one another
    in a preconfigured order.

    The **layer configuration** determines which chains run in a given layer as well as serial execution sequence
    position and membership. The **execution configuration** specifies what methods are called for each region, as well
    as the relative order in which these methods are called once a region is run.

    Side effects:

    - While links between regions within the same layer are permitted, they carry the potential of introducing undesirable race conditions

    - After a layer executes, the resources it was using (eg. LLMLink) are freed for use by other layers

    - Regions sharing the same resource within a layer must be grouped into chains to serialize utilization. This can be useful if a layer contains regions with mixed latencies – low-latency regions can run serially while a high-latency region blocks a dedicated resource.

    - The computation speed of each layer is determined by the speed of the slowest serial execution sequence within it.

    - A region may be called more than once while a layer is being executed. In such a case, all calls to one region are treated as a serial execution sequence that runs when the region is called.

    - There is nothing preventing a region from being assigned to more than one execution layer, provided the above considerations are taken into account.

    Note:
        Execution layers are concurrency groups. Within a layer, chains define serial execution sequences that run
        concurrently with other chains in the same layer.

        Execution layers differ from perceptron layers in a neural network. Conventional layer membership is determined
        by the position of a node in a network graph. Membership in an execution layer is determined by the relative
        state of a node with respect to the execution sequence – a dimension which maps one-to-one to a segment of runtime.

    Example 1:
        Layer configuration to execute "foo", then "bar" while "baz" runs in parallel

        >>> layer = {"chain1":["foo","bar"],"chain2":["baz"]}
        >>> layer = dict(
                        chain1=["foo","bar"],
                        chain2=["baz"]
                        )

    Example 2:
        Region execution configurations for the above layer that causes "foo" and "bar" to make_questions while
        "baz" runs make_answers, then ponder_deeply in parallel.

        >>> executions = [("foo", "make_questions"), ("bar", "make_questions"), ("baz", "make_answers"), ("baz", "ponder_deeply")]
        >>> executions = [("bar", "make_questions"), ("baz", "make_answers"), ("foo", "make_questions"), ("baz", "ponder_deeply")]

        **Incorrect** (ponder_deeply executes before make_answers):

        >>> executions = [("bar", "make_questions"), ("baz", "ponder_deeply"), ("foo", "make_questions"), ("baz", "make_answers")]
    """

    def __init__(self,
                 layer_config: list[dict] = None,
                 execution_config: list[list[tuple]] = None,
                 execution_order: list[int] = None,
                 ):
        """
        Initialize Orchestrator with execution planning configurations.

        Args:
            layer_config: List of dictionaries where each dict maps chain names to region lists
                          for concurrent execution within a layer. Defaults to empty list.
            execution_config: List of lists for each layer containing tuples specifying (region, method) execution
                              sequences. Defaults to empty list.
            execution_order: List of layer indices defining custom execution sequence.
                             Defaults to sequential order if not provided.

        Note:
            Uses `set_list()` utility to convert None inputs to empty lists. Configuration
            validation occurs during `verify()` calls.
        """
        self.layer_config = set_list(layer_config)
        self.execution_config = set_list(execution_config)
        self.execution_order = set_list(execution_order)

    def __str__(self):
        """
        Return human-readable string representation of Orchestrator configuration.

        Returns:
            String containing formatted layer, execution, and order configurations.
        """
        return f"LayerConfig: {self.layer_config}\nExecutionConfig: {self.execution_config}\nExecutionOrder: {self.execution_order}"

    def pad(self, length: int):
        """
        Extend configurations to match specified length by adding empty elements.

        Args:
            length: Target length for both layer_config and execution_config lists.

        Note:
            Adds empty dictionaries to layer_config and empty lists to execution_config
            until they reach the specified length. Uses `set_list()` internally for safety.
        """
        for n in range(len(self.layer_config), length):
            self.layer_config.append({})
        for n in range(len(self.execution_config), length):
            self.execution_config.append([])

    def region_layers(self, region: str) -> list[int]:
        """
        Identify layers containing a specified region.

        Args:
            region: Name of the region to search for.

        Returns:
            List of layer indices where the region appears in layer_config.

        Example:
            >>> orchestrator.region_layers("foo")
            [0, 2]  # Region 'foo' appears in layers 0 and 2
        """
        associated_layers = []
        for index, layer_plan in enumerate(self.layer_config):
            if any(region in chain for chain in layer_plan.values()):
                associated_layers.append(index)
        return associated_layers

    def methods_in_layer(self, layer: int, region: str) -> list:
        """
        Retrieve execution methods for a region within a specific layer.

        Args:
            layer: Target layer index.
            region: Region name to query.

        Returns:
            List of method names in execution order for the region in the layer.
            Empty list if layer is out of range or region has no methods.

        Note:
            Methods are returned in the order defined in execution_config[layer].
            Logs error if layer index exceeds configuration length.
        """
        if layer >= len(self.execution_config):
            logging.error(f"Layer {layer} out of range")
            return []
        methods = []
        for exec_tuple in self.execution_config[layer]:
            if region == exec_tuple[0]:
                methods.append(exec_tuple[1])
        return methods

    def remove_method(self, layer: int, region: str, method: str) -> bool:
        """
        Remove a specific method execution from a region in a layer.

        Args:
            layer: Target layer index.
            region: Region name.
            method: Method name to remove.

        Returns:
            True if method was successfully removed, False otherwise.

        Note:
            Uses `check_execution_entry()` implicitly via tuple comparison.
            Logs error if method not found or layer out of range.
        """
        if layer >= len(self.execution_config):
            logging.error(f"Layer {layer} out of range")
            return False

        for exec_tuple in self.execution_config[layer]:
            if region == exec_tuple[0] and method == exec_tuple[1]:
                self.execution_config[layer].remove(exec_tuple)
                return True
        logging.error(f"'{method}' for region '{region}' not found in layer {layer}")
        return False

    def remove_methods(self, layer: int, region: str) -> int:
        """
        Remove all method executions for a region in a layer.

        Args:
            layer: Target layer index.
            region: Region name.

        Returns:
            Number of methods removed (0 if none found).

        Note:
            Collects all matching entries first to avoid modification during iteration.
            Logs error if no methods found or layer out of range.
        """
        if layer >= len(self.execution_config):
            logging.error(f"Layer {layer} out of range")
            return 0

        # Collect items to remove first
        to_remove = []
        for exec_tuple in self.execution_config[layer]:
            if region == exec_tuple[0]:
                to_remove.append(exec_tuple)

        # Remove all at once
        for item in to_remove:
            self.execution_config[layer].remove(item)

        methods_removed = len(to_remove)

        if not methods_removed:
            logging.error(f"No methods found for region '{region}' in layer {layer}")
        return methods_removed

    def append_method(self, layer: int, region: str, method: str) -> bool:
        """
        Add a new method execution for a region in a layer.

        Args:
            layer: Target layer index.
            region: Region name.
            method: Method name to add.

        Returns:
            True if method was successfully added, False if duplicate exists.

        Note:
            Uses `check_execution_entry()` to validate (region, method) tuple.
            Pads execution_config if layer index exceeds current length.
            Logs error if method already exists in layer.
        """
        new_tuple = check_execution_entry((region, method))
        if layer >= len(self.execution_config):
            self.pad(layer + 1)
        original_methods = self.methods_in_layer(layer, region)
        if not original_methods or method not in original_methods:
            self.execution_config[layer].append(new_tuple)
            logging.info(f"Method '{method}' added for region '{region}' in layer {layer}")
            return True
        logging.error(f"'{method}' for region '{region}' already in layer {layer}, not appending")
        return False

    def replace_method(self, layer: int, region: str, method_to_replace: str, new_method: str) -> bool:
        """
        Replace an existing method with a new one for a region in a layer.

        Args:
            layer: Target layer index.
            region: Region name.
            method_to_replace: Existing method name to replace.
            new_method: New method name.

        Returns:
            True if replacement was successful, False otherwise.

        Note:
            Validates via `check_execution_entry()` for new method.
            Logs specific errors for: missing region, self-replacement, missing old method,
            or duplicate new method.
            Raises RuntimeError if replacement fails unexpectedly.
        """
        original_methods = self.methods_in_layer(layer, region)
        old_tuple = (region, method_to_replace)  # This is getting replaced anyway, so no need to check
        new_tuple = check_execution_entry((region, new_method))

        if not original_methods:
            logging.error(f"Region '{region}' not found in execution configuration for layer {layer}")
            return False

        if method_to_replace == new_method:
            logging.error(f"Attempted to replace '{method_to_replace}' with itself")
            return False

        if method_to_replace not in original_methods:
            logging.error(f"'{method_to_replace}' not found for region '{region}' in layer {layer}")
            return False

        if new_method in original_methods:
            logging.error(f"'{new_method}' already exists for region '{region}' in layer {layer}")
            return False

        for idx, exec_tuple in enumerate(self.execution_config[layer]):
            if exec_tuple == old_tuple:
                self.execution_config[layer][idx] = new_tuple
                logging.info(
                    f"Replaced '{method_to_replace}' with '{new_method}' for region '{region}' in layer {layer}")
                return True
        raise RuntimeError("Method should have been replaced but was not")

    def region_profile(self, region: str) -> dict:
        """
        Generate execution profile for a region across all layers.

        Args:
            region: Region name to profile.

        Returns:
            Dictionary mapping layer indices to lists of methods executed in that layer.
            Empty dict if region has no executions.

        Example:
            >>> orchestrator.region_profile("baz")
            {0: ["make_answers"], 1: ["ponder_deeply"]}
        """
        profile = {}
        for index, layer in enumerate(self.execution_config):
            layer_profile = self.methods_in_layer(index, region)
            if layer_profile:
                profile[index] = layer_profile
        if not profile:
            logging.error(f"'{region}' not found in execution configuration")
        return profile

    def append_to_layer(self, layer_index: int, chain: str, region: str) -> bool:
        """
        Add a region to a chain within a layer.

        Args:
            layer_index: Target layer index.
            chain: Chain name within the layer.
            region: Region name to add.

        Returns:
            True if region was added, False if already present.

        Note:
            Pads layer_config if layer_index exceeds current length.
            Checks for region existence in any chain before adding.
            Logs success on addition, returns False if region exists elsewhere.
        """
        if layer_index >= len(self.layer_config):
            self.pad(layer_index + 1)

        work_layer = self.layer_config[layer_index]

        # Check if the region is already present in any chain of the layer
        for existing_chain in work_layer.values():
            if region in existing_chain:
                return False  # Region is already present, so do not append

        # Append the region to the specified chain
        if chain not in work_layer:
            work_layer[chain] = []
        work_layer[chain].append(region)
        self.layer_config[layer_index] = work_layer
        return True

    def remove_from_layer(self, layer_index: int, region: str) -> bool:
        """
        Remove a region from a layer's configuration.

        Args:
            layer_index: Target layer index.
            region: Region name to remove.

        Returns:
            True if region was successfully removed, False otherwise.

        Note:
            Uses `trim_list()` to remove empty layers after deletion.
            Logs removal success and chain deletion if applicable.
            Logs error if region not found in layer.
        """
        region_deleted = False
        chain_deleted = ''

        # Get the layer dictionary
        try:
            work_layer = self.layer_config[layer_index]
        except IndexError:
            logging.error(f"Layer {layer_index} does not exist")
            return False

        # Iterate through chains (keys) and their values
        for chain_name, chain in work_layer.items():
            if region in chain:
                chain.remove(region)  # remove region from the chain list

                # If chain becomes empty, remove the chain
                if not chain:
                    del work_layer[chain_name]
                    chain_deleted = chain_name

                region_deleted = True
                break

        # Update layer config if changes were made
        if region_deleted:
            self.layer_config[layer_index] = work_layer
            logging.info(f"Region '{region}' removed from layer {layer_index}")
            if chain_deleted:
                logging.info(f"Empty chain '{chain_deleted}' removed from layer {layer_index}")
                layers_trimmed = trim_list(self.layer_config)
                if layers_trimmed:
                    logging.info(f"Removed {layers_trimmed} empty layers from the layer configuration")
            return True
        logging.error(f"Region '{region}' not found in layer {layer_index}")
        return False

    def save(self, output_path: str):
        """
        Serialize configuration to JSON file.

        Args:
            output_path: Path to save configuration (e.g., 'orchestrator.json').

        Note:
            Saves layer_config, execution_config, and execution_order as JSON.
            Overwrites existing files without confirmation.
        """
        with open(output_path, "w") as f:
            json.dump({
                "layer_config": self.layer_config,
                "execution_config": self.execution_config,
                "execution_order": self.execution_order
            }, f)

    def load(self, path: str) -> bool:
        """
        Deserialize configuration from JSON file.

        Args:
            path: Path to configuration file.

        Returns:
            True if loading succeeded, False if file invalid or missing keys.

        Note:
            Uses `pathlib` for path handling. Logs detailed loading status.
            Resets configurations to empty lists if keys missing.
            Validates all three required keys (layer_config, execution_config, execution_order).
        """
        posix_path = pathlib.PurePosixPath(path)

        with open(str(posix_path), "r") as f:
            data = json.load(f)
            logging.info(f"Loaded data from '{posix_path.name}'")

        if not 'layer_config' in data and not 'execution_config' in data and not 'execution_order' in data:
            logging.error(
                "None of layer_config, execution_config or execution_order keys found. Unable to load the data.")
            return False
        if 'layer_config' in data:
            self.layer_config = data['layer_config']
            logging.info("Layer configuration loaded successfully")
        else:
            self.layer_config = []
        if 'execution_config' in data:
            raw_execution_config = data['execution_config']
            new_execution_config = []
            for raw_layer in raw_execution_config:
                new_execution_config.append([tuple(x) for x in raw_layer])
            self.execution_config = new_execution_config
            logging.info("Execution configuration loaded successfully")
        else:
            self.execution_config = []
        if 'execution_order' in data:
            self.execution_order = data['execution_order']
            logging.info("Execution order loaded successfully")
        else:
            self.execution_order = []
        return True

    def regions(self) -> list:
        """
        Returns a list of all unique regions defined in the layer configuration.

        Side Effects:
            - If a region is present in the execution configuration, but not in the layer configuration, it will
              be omitted from this output.
        """
        all_regions = set()
        for layer in self.layer_config:
            for chain in layer.values():
                all_regions.update(chain)
        return list(all_regions)

    def verify(self) -> bool:
        """
        Validate configuration consistency and integrity.

        Returns:
            True if configuration passes all critical checks, False otherwise.

        Validation checks include:
            - Layer/execution configuration length mismatches
            - Silent layers (empty layer config but non-empty execution)
            - Missing layers (non-empty execution but empty layer config)
            - Invalid execution_order indices
            - Regions with no execution methods
            - Duplicate regions within layers
            - Invalid execution entries (via `check_execution_entry`)

        Note:
            Logs warnings/errors for all inconsistencies. Does not modify configuration.
            Returns False if critical errors found (e.g., duplicate regions).
        """
        valid = True

        # Check layer_config and execution_config lengths
        layer_count = len(self.layer_config)
        execution_count = len(self.execution_config)

        # Handle length discrepancies
        if layer_count > execution_count:
            logging.warning(
                f"Trailing silent layers detected: {layer_count - execution_count} layers in layer_config have no execution_config entries")
        elif layer_count < execution_count:
            logging.warning(
                f"Missing layers detected: {execution_count - layer_count} execution_config entries have no corresponding layer_config entries")

        # Check layers within common range
        common_range = min(layer_count, execution_count)
        for i in range(common_range):
            layer_empty = not self.layer_config[i] or all(not chain for chain in self.layer_config[i].values())
            execution_empty = not self.execution_config[i]

            # Silent layer check (empty layer but non-empty execution)
            if layer_empty and not execution_empty:
                logging.warning(f"Layer {i} is silent: empty layer configuration but non-empty execution configuration")

            # Missing layer check (non-empty execution but empty layer)
            if not layer_empty and execution_empty:
                logging.warning(f"Layer {i} is missing: execution configuration present but empty layer configuration")

        # Check execution_order
        if not self.execution_order:
            logging.warning(
                "No execution_order provided. System will default to iterating through layers sequentially.")
        else:
            # Validate execution_order indices
            for idx in self.execution_order:
                if idx < 0 or idx >= layer_count:
                    logging.error(
                        f"Execution order contains invalid layer index {idx} (must be between 0 and {layer_count - 1})")
                    valid = False

            # Check for missing layers in execution_order
            missing_layers = [i for i in range(layer_count) if i not in self.execution_order]
            if missing_layers:
                logging.warning(f"Layers {missing_layers} are missing from execution_order and will be silent")

        # Check regions with no methods
        all_regions = self.regions()
        for region in all_regions:
            has_methods = False
            for layer_idx in range(execution_count):
                if self.methods_in_layer(layer_idx, region):
                    has_methods = True
                    break
            if not has_methods:
                logging.warning(f"Region '{region}' has no execution methods defined")

        # Validate each layer in layer_config
        for layer_idx, layer in enumerate(self.layer_config):
            # Check for empty chains
            for chain_name, chain in layer.items():
                if not chain:
                    logging.warning(f"Layer {layer_idx}: chain '{chain_name}' is empty")

            # Check for duplicate regions within layer
            all_regions_in_layer = []
            for chain in layer.values():
                all_regions_in_layer.extend(chain)

            if len(all_regions_in_layer) != len(set(all_regions_in_layer)):
                duplicate_regions = [r for r in all_regions_in_layer if all_regions_in_layer.count(r) > 1]
                logging.error(f"Layer {layer_idx} contains duplicate regions: {duplicate_regions}")
                valid = False

            # Check regions with no methods in this layer
            for region in all_regions_in_layer:
                if not self.methods_in_layer(layer_idx, region):
                    logging.warning(f"Region '{region}' in layer {layer_idx} has no execution methods")

        # Validate each entry for each layer in execution_config
        for layer_executions in self.execution_config:
            for entry in layer_executions:
                try:
                    check_execution_entry(entry)
                except AssertionError as e:
                    logging.warning(f"Invalid execution entry will be ignored: {entry}. {e}")

        return valid

        # === Validation pseudocode ===
        # ideally has same number of layers in layer_config and execution_config
            # len(layer_config) > len(execution_config)
                # warn about trailing silent layers (ie, not listed in execution config but present in layer config)
            # len(layer_config) < len(execution_config)
                # warn about missing layers (ie, listed in execution config but absent from layer config)
            # for indices in range of shortest of execution_config and layer_config
                # warn about silent layers (ie empty layer, but nonempty execution entry)
                # warn about missing layers (ie, nonempty execution entry, but empty layer)
                # warn about layer indices that are both missing and silent (ie. listed in neither)
        # if no execution_order:
            # warn that system will default to iterating through layers sequentially
        # if execution_order is nonempty:
            # all execution_order items must be >0 and < len(layer_config)
                # fail the verify if this is not the case
            # every layer index can be found in execution_order
                # warn which layers are missing from execution order, and that they will be silent
        # for each unique region:
            # warn if any regions runs no methods
        # for each layer in layer_config:
            # each chain is associated with at least one region - warn for any empty chains
            # no duplicate regions are allowed to be present in a given single layer
                # fail the verify if this is not the case
            # no duplicate chains within a layer
                # fail the verify if this is not the case
            # each region runs at least one method for same layer in execution_config - warn for silent regions
        # Validate each entry for each layer in execution_config using check_execution_entry

    # SUGGEST: Add options to clean silent elements and invalid entries from configuration
