import logging
from dataclasses import dataclass
from typing import Any
import asyncio
from functools import partial

from region_types import *
from region import *
from postmaster import Postmaster
from orchestrator import Orchestrator
from region_registry import RegionRegistry

def cross_verify(
        registry: RegionRegistry,
        orchestrator: Orchestrator,
        postmaster: Postmaster,
        verify_registry: bool = True,
        rebuild_regions: bool = True,
        verify_orchestrator: bool = True
) -> bool:
    """Perform comprehensive cross-verification of system configuration components.

    Validates consistency between the region registry, orchestrator execution plan, and postmaster CC region.
    Ensures all regions are properly defined, region types are valid, and all required methods in execution
    profiles are callable. Logs detailed discrepancies and returns False if any verification fails.

    Verification includes:
    - Registry integrity (with optional rebuild)
    - Orchestrator configuration validity
    - Consistency between orchestrator regions and registry regions
    - CC region presence and validity (must be ListenerRegion)
    - Callability of all methods specified in region profiles
    - Additional verification for ListenerRegions

    Parameters:
        registry (RegionRegistry): Region registry containing all defined regions
        orchestrator (Orchestrator): Orchestrator managing execution plans and region profiles
        postmaster (Postmaster): Postmaster providing CC region configuration
        verify_registry (bool, optional): Whether to verify registry integrity. Default: True
        rebuild_regions (bool, optional): Whether to rebuild region instances during verification.
            When combined with verify_registry=True: rebuilds and verifies
            When verify_registry=False: rebuilds without verification. Default: True
        verify_orchestrator (bool, optional): Whether to verify orchestrator configuration. Default: True

    Returns:
        bool: True if all verifications pass without discrepancies, False otherwise

    Notes:
        - CC region must exist in registry and be a ListenerRegion (failure if not)
        - CC region not in orchestrator execution plan triggers warning but not failure
        - Non-callable methods in region profiles cause verification failure
        - ListenerRegions undergo additional validation via their verify() method
        - All discrepancies are logged with specific error messages
        - Returns True only if ALL verifications pass (registry, orchestrator, cross-checks, method validity)
    """
    orchestrator_regions = orchestrator.regions()
    registry_regions = registry.names
    cc_region = postmaster.cc

    valid = True

    # Verify and/or build the registry
    if verify_registry and rebuild_regions:
        logging.info("Verifying and rebuilding the region registry")
        built = False
        try:
            built = registry.build_regions(overwrite=True)
        except Exception as e:
            logging.error(f"Exception while building registry: {e}")
            valid = False
        if not built:
            logging.error("Failed to build the registry")
            valid = False
    elif verify_registry and not rebuild_regions:
        logging.info("Verifying the registry without rebuilding region instances")
        verified = False
        try:
            verified = registry.verify()
        except Exception as e:
            logging.error(f"Exception while verifying registry: {e}")
            valid = False
        if not verified:
            logging.error("Failed to verify the registry")
            valid = False
    elif rebuild_regions and not verify_registry:
        logging.info("Rebuilding the region without verification")
        built = False
        try:
            built = registry.build_regions(overwrite=True, verify=False)
        except Exception as e:
            logging.error(f"Exception while building registry: {e}")
            valid = False
        if not built:
            logging.error("Failed to build the registry")
            valid = False
    else:
        logging.info("Skipping registry verification and rebuild")

    # Verify the orchestrator
    if verify_orchestrator:
        logging.info("Verifying the orchestrator")
        verified = False
        try:
            verified = orchestrator.verify()
        except Exception as e:
            logging.error(f"Exception while verifying orchestrator: {e}")
            valid = False
        if not verified:
            logging.error("Failed to verify orchestrator")
            valid = False
    else:
        logging.info("Skipping orchestrator verification")

    # Check for region discrepancies between orchestrator and registry
    logging.info("Beginning cross-verification")
    try:
        assert set(orchestrator_regions) == set(registry_regions), "Orchestrator and registry have different region sets"
    except AssertionError as e:
        logging.error(str(e))
        orchestrator_only = list(set(orchestrator_regions) - set(registry_regions))
        registry_only = list(set(registry_regions) - set(orchestrator_regions))

        if orchestrator_only:
            logging.info(f"Orchestrator-only regions: {', '.join(orchestrator_only)}")
        if registry_only:
            logging.info(f"Registry-only regions: {', '.join(registry_only)}")

        valid = False

    # Check for CC region discrepancy
    if cc_region:
        logging.info(f"CC region in postmaster: '{cc_region}'")
        if cc_region not in registry_regions:
            logging.error(f"CC region '{cc_region}' is not defined in the registry name list")
            valid = False
        if cc_region not in orchestrator_regions:
            logging.error(f"CC region '{cc_region}' is not included in the execution configuration.")
        else:
            cc_exists = True
            try:
                logging.info("Trying to access CC region directly")
                registry[cc_region]
            except ValueError or AttributeError as e:
                logging.error(f"{e}")
                cc_exists = False
                valid = False

            if cc_exists and class_str_from_instance(registry[cc_region]) == 'ListenerRegion':
                try:
                    listener_valid = registry[cc_region].verify(orchestrator)
                except Exception as e:
                    logging.error(f"ListenerRegion {cc_region} verification raised an exception: {e}")
                    listener_valid = False
                if not listener_valid:
                    logging.error(f"ListenerRegion {cc_region} verification failed")
                    valid = False
            else:
                logging.error("CC region is not a ListenerRegion")
                valid = False

    for region in registry.regions:

        # Ensure there's a non-empty region type
        registry_type = None

        try:
            registry_index = registry.names.index(region.name)
            registry_type = registry.regions[registry_index].type
        except ValueError:
            logging.warning(f"'{region}' not found in RegionRegistry")

        if registry_type:
            determined_type = registry_type
        else:
            logging.warning(f"Region '{region.name}' has no type specified in registry. Looking up in dictionary instead.")
            try:
                determined_type = class_str_from_instance(registry[region.name])
            except NameError as e:
                logging.error(f"Could not determine type for region '{region.name}': {e}")
                valid = False
                continue

        # Check if all references in region profile are methods or functions
        profile = orchestrator.region_profile(region.name)
        methods_good = True
        for method_name in set([x for xs in [*profile.values()] for x in xs]):
            try:
                ref = getattr(registry[region.name], method_name).__qualname__

            except AttributeError:
                logging.error(f"Nonexistent method '{method_name}' called for {determined_type} '{region}'")
                methods_good = False
        if methods_good:
            logging.info(f"Planned calls to '{region.name}' are valid for class {determined_type}.")
        else:
            valid = False

        # Extra steps for ListenerRegions
        if determined_type == 'ListenerRegion':
            try:
                registry[region.name].verify(orchestrator)
            except Exception as e:
                logging.error(f"Verification raised an exception: {e}")
                valid = False

    if valid: logging.info("Run configuration is valid.")
    else: logging.error("Run configuration is invalid.")
    return valid

