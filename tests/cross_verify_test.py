from functools import partial

import pytest
from unittest.mock import MagicMock, patch

from tests.mock_regions import MockRegion, MockListenerRegion
from postmaster import Postmaster
from region import BaseRegion
from region_registry import RegionRegistry, RegionEntry
from orchestrator import Orchestrator
from executor import cross_verify
from region_types import class_str_from_instance, region_dictionary


@pytest.fixture
def mock_registry():
    mock = MagicMock(spec=RegionRegistry)
    mock.names = []
    mock.regions = []
    mock.build_regions.return_value = True
    mock.verify.return_value = True
    return mock


@pytest.fixture
def mock_orchestrator():
    mock = MagicMock(spec=Orchestrator)
    mock.regions.return_value = []
    mock.verify.return_value = True
    mock.region_profile.return_value = {}
    mock.execution_config = []
    return mock


@pytest.fixture
def mock_postmaster():
    mock = MagicMock(spec=Postmaster)
    mock.cc = None
    return mock

'''
# Mock class_str_from_instance implementation
def mock_str_from_class(type_str):
    if type_str == 'Region':
        return MockRegion
    elif type_str == 'ListenerRegion':
        return MockListenerRegion
    return None
'''


# Test successful verification
def test_cross_verify_success(mock_postmaster, caplog):
    # Setup valid configuration
    entry_a = RegionEntry('A','MockRegion','mock_method',region=MockRegion('A'))
    entry_b = RegionEntry('B','MockRegion','mock_method',region=MockRegion('B'))
    registry = RegionRegistry()
    registry.register(entry_a)
    registry.register(entry_b)

    orchestrator = Orchestrator()
    orchestrator.layer_config = [{"chain":["A", "B"]}]
    orchestrator.execution_config = [[('A', 'mock_method'), ('B', 'mock_method')]]
    orchestrator.execution_order = [0]

    result = cross_verify(registry, orchestrator, mock_postmaster)
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    print(orchestrator.regions())
    print(registry.names)
    assert result is True


# Test registry build failure
def test_cross_verify_registry_build_failure(mock_registry, mock_orchestrator, mock_postmaster):
    mock_registry.build_regions.return_value = False
    mock_registry.names = ['A']
    entry_a = RegionEntry('A', 'MockRegion', 'mock_method', region=MockRegion('A'))
    mock_registry.regions = [entry_a]

    mock_orchestrator.regions.return_value = ['A']
    mock_orchestrator.region_profile.return_value = {0: ['make_questions']}

    result = cross_verify(
        mock_registry,
        mock_orchestrator,
        mock_postmaster,
        verify_registry=True,
        rebuild_regions=True
    )
    assert result is False


# Test registry verify failure
def test_cross_verify_registry_verify_failure(mock_registry, mock_orchestrator, mock_postmaster):
    mock_registry.verify.return_value = False
    mock_registry.names = ['A']

    result = cross_verify(
        mock_registry,
        mock_orchestrator,
        mock_postmaster,
        verify_registry=True,
        rebuild_regions=False
    )
    assert result is False


# Test orchestrator verification failure
def test_cross_verify_orchestrator_failure(mock_registry, mock_orchestrator, mock_postmaster):
    mock_orchestrator.verify.return_value = False
    mock_registry.names = ['A']
    entry_a = RegionEntry('A', 'MockRegion', 'mock_method', region=MockRegion('A'))
    mock_registry.regions = [entry_a]
    mock_orchestrator.regions.return_value = ['A']

    result = cross_verify(
        mock_registry,
        mock_orchestrator,
        mock_postmaster,
        verify_orchestrator=True
    )
    assert result is False


# Test region discrepancy
def test_cross_verify_region_discrepancy(mock_registry, mock_orchestrator, mock_postmaster):
    mock_registry.names = ['A']
    entry_a = RegionEntry('A', 'MockRegion', 'mock_method', region=MockRegion('A'))
    mock_registry.regions = [entry_a]
    mock_orchestrator.regions.return_value = ['A', 'B']

    result = cross_verify(mock_registry, mock_orchestrator, mock_postmaster)
    assert result is False


# Test CC region not in registry
def test_cross_verify_cc_not_in_registry(mock_orchestrator, mock_postmaster, caplog):
    mock_postmaster.cc = 'CC'
    entry_a = RegionEntry('A', 'MockRegion', 'mock_method', region=MockRegion('A'))
    registry = RegionRegistry()
    registry.register(entry_a)
    mock_orchestrator.regions.return_value = ['A', 'CC']

    result = cross_verify(registry, mock_orchestrator, mock_postmaster)
    print("=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is False


# Test CC region not ListenerRegion
def test_cross_verify_cc_not_listener_region(mock_registry, mock_orchestrator, mock_postmaster):
    mock_postmaster.cc = 'CC'
    mock_registry.names = ['CC']
    entry_c = RegionEntry('CC', 'MockRegion', 'mock_method', region=MockRegion('CC'))
    mock_registry.regions = [entry_c]
    mock_registry.__getitem__.return_value = MockRegion('CC')
    mock_orchestrator.regions.return_value = ['CC']

    result = cross_verify(mock_registry, mock_orchestrator, mock_postmaster)
    assert result is False


# Test ListenerRegion verification failure
def test_cross_verify_listener_region_failure(mock_registry, mock_orchestrator, mock_postmaster):
    mock_postmaster.cc = 'CC'
    mock_registry.names = ['CC']
    mock_listener = MockListenerRegion('CC')
    listener_entry = RegionEntry('CC', 'MockListenerRegion', 'things', region=mock_listener)
    mock_registry.regions = [listener_entry]
    mock_registry.__getitem__.return_value = mock_listener
    mock_orchestrator.regions.return_value = ['CC']

    # Mock invalid region profile
    mock_orchestrator.region_profile.return_value = {1: ['start'], 2: ['stop']}
    mock_orchestrator.execution_config = [[], [], []]

    result = cross_verify(mock_registry, mock_orchestrator, mock_postmaster)
    assert result is False


# Test non-callable method
def test_cross_verify_non_callable_method(mock_registry, mock_orchestrator, mock_postmaster, caplog):
    mock_registry.names = ['A']
    entry_a = RegionEntry('A', 'MockRegion', 'non_callable_method', region=MockRegion('A'))
    mock_registry.regions = [entry_a]
    mock_orchestrator.regions.return_value = ['A']
    mock_orchestrator.region_profile.return_value = {0: ['invalid_method']}

    result = cross_verify(mock_registry, mock_orchestrator, mock_postmaster)
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is False


# Test region type fallback
def test_cross_verify_region_type_fallback(mock_orchestrator, mock_postmaster, caplog):
    # Create region with empty type
    mock_region = MockRegion('A')
    entry = RegionEntry(name='A', task='things', region=mock_region)
    registry = RegionRegistry([entry])
    mock_orchestrator.regions.return_value = ['A']
    mock_orchestrator.region_profile.return_value = {0: ['mock_method']}

    result = cross_verify(registry, mock_orchestrator, mock_postmaster, verify_registry=False, rebuild_regions=False)
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")

    assert result is True


# Test CC region not in orchestrator (two error points, and shows CC is only in the registry)
def test_cross_verify_cc_not_in_orchestrator(mock_registry, mock_orchestrator, mock_postmaster, caplog):
    mock_postmaster.cc = 'CC'
    mock_registry.names = ['CC']
    mock_listener = MockListenerRegion('CC')
    entry = RegionEntry('CC','MockListenerRegion','things')
    mock_registry.regions = [entry]
    mock_registry.__getitem__.return_value = mock_listener
    mock_orchestrator.regions.return_value = []
    mock_orchestrator.execution_config = []
    mock_orchestrator.layer_config=[{"chain":["CC"]}]

    result = cross_verify(mock_registry, mock_orchestrator, mock_postmaster)
    print("\n=== CAPLOG ===\n" + caplog.text + "=== END CAPLOG ===")
    assert result is False
    assert "Orchestrator and registry have different region sets" in caplog.text
    assert "Registry-only regions: CC"
    assert "CC region 'CC' is not included in the execution configuration." in caplog.text


# Test verification flags combination
def test_cross_verify_flag_combinations(mock_orchestrator, mock_postmaster, caplog):
    registry = RegionRegistry()
    entry_a = RegionEntry('A', 'MockRegion', 'mock_method', region=MockRegion('A'))
    registry.register(entry_a)
    mock_orchestrator.regions.return_value = ['A']
    mock_orchestrator.region_profile.return_value = {0: ['mock_method']}

    verify_combos = partial(cross_verify, registry, mock_orchestrator, mock_postmaster)

    # Flag combinations
    assert verify_combos(True, True, True)
    assert verify_combos(False, True, True)
    assert verify_combos(True, False, True)
    assert verify_combos(True, True, False)
    assert verify_combos(True, False, False)
    assert verify_combos(False, True, False)
    assert verify_combos(False, False, True)
    assert verify_combos(False, False, False)