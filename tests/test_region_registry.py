import json
import unittest
import tempfile
import os
from unittest.mock import MagicMock, patch

from region_registry import RegionRegistry, RegionEntry
from mock_regions import MockRegion, MockRAGRegion


class TestRegionRegistry(unittest.TestCase):
    def setUp(self):
        # Mock dependencies
        self.mock_rag = MagicMock()
        self.mock_llm = MagicMock()

        # Create registry with mock defaults
        self.registry = RegionRegistry(
            default_rag=self.mock_rag,
            default_llm=self.mock_llm
        )

        # Setup mock region types
        self.mock_region_types = [
            {"name": "MockRegion", "class": MockRegion},
            {"name": "MockRAGRegion", "class": MockRAGRegion}
        ]

    async def asyncSetUp(self):
        """Initialize async components if needed"""
        pass

    async def test_initialization(self):
        """Verify RegionRegistry initializes correctly"""
        self.assertEqual(len(self.registry), 0)
        self.assertFalse(self.registry.live)
        self.assertEqual(self.registry.default_rag, self.mock_rag)
        self.assertEqual(self.registry.default_llm, self.mock_llm)
        self.assertEqual(self.registry.regions, [])
        self.assertEqual(self.registry.names, [])

    async def test_register_region(self):
        """Test region registration workflow"""
        entry = RegionEntry(
            name="test_region",
            type="MockRegion",
            task="test task",
            connections=["other_region"]
        )

        registered = self.registry.register(entry)
        self.assertTrue(registered)
        self.assertEqual(len(self.registry), 1)
        self.assertEqual(self.registry.names, ["test_region"])
        self.assertEqual(self.registry.regions[0].name, "test_region")

    async def test_deregister_region(self):
        """Test region deregistration"""
        entry = RegionEntry(
            name="test_region",
            type="MockRegion",
            task="test task"
        )
        self.registry.register(entry)

        removed = self.registry.deregister("test_region")
        self.assertTrue(removed)
        self.assertEqual(len(self.registry), 0)
        self.assertEqual(self.registry.names, [])

    async def test_load_json(self):
        """Test loading regions from JSON file"""
        # Create temporary JSON file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            test_data = [
                {
                    "name": "sales",
                    "type": "MockRegion",
                    "task": "handle sales inquiries",
                    "connections": ["customer_support"]
                },
                {
                    "name": "customer_support",
                    "type": "MockRAGRegion",
                    "task": "provide customer assistance",
                    "connections": ["sales"]
                }
            ]
            json.dump(test_data, tmp)
            tmp_path = tmp.name

        # Patch class_from_str to return mock classes
        with patch('region_types.class_from_str', side_effect=lambda x:
        MockRegion if x == "MockRegion" else MockRAGRegion):
            loaded = self.registry.load(tmp_path)
            self.assertTrue(loaded)
            self.assertEqual(len(self.registry), 2)
            self.assertEqual(self.registry.names, ["sales", "customer_support"])

        # Cleanup
        os.unlink(tmp_path)

    async def test_load_invalid_json(self):
        """Test handling of invalid JSON files"""
        # Create invalid JSON file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as tmp:
            tmp.write("invalid json")
            tmp_path = tmp.name

        loaded = self.registry.load(tmp_path)
        self.assertFalse(loaded)
        self.assertEqual(len(self.registry), 0)

        # Cleanup
        os.unlink(tmp_path)

    async def test_verify_valid(self):
        """Test verification of valid registry configuration"""
        # Setup valid registry
        entry1 = RegionEntry(
            name="sales",
            type="MockRegion",
            task="handle sales inquiries",
            connections=["customer_support"]
        )
        entry2 = RegionEntry(
            name="customer_support",
            type="MockRAGRegion",
            task="provide customer assistance",
            connections=["sales"]
        )
        self.registry.regions = [entry1, entry2]
        self.registry._update_names()

        issues, warnings = self.registry.verify()
        self.assertEqual(len(issues), 0)
        self.assertEqual(len(warnings), 0)

    async def test_verify_invalid_connections(self):
        """Test detection of invalid connections"""
        # Setup invalid registry
        entry = RegionEntry(
            name="sales",
            type="MockRegion",
            task="handle sales inquiries",
            connections=["invalid_region"]
        )
        self.registry.regions = [entry]
        self.registry._update_names()

        issues, warnings = self.registry.verify()
        self.assertEqual(len(issues), 1)
        self.assertIn("Connection to 'invalid_region'", issues[0])

    async def test_build_regions_success(self):
        """Test successful region building"""
        # Setup registry with mock region
        entry = RegionEntry(
            name="sales",
            type="MockRegion",
            task="handle sales inquiries",
            connections=[]
        )
        self.registry.regions = [entry]
        self.registry._update_names()

        # Build regions
        success = self.registry.build_regions()
        self.assertTrue(success)
        # 'live' flag for partial write protection not yet implemented, and built != live
        # self.assertTrue(self.registry.live)
        self.assertIsNotNone(self.registry["sales"])
        self.assertEqual(self.registry["sales"].name, "sales")

    async def test_build_regions_with_defaults(self):
        """Test region building with default dependencies"""
        # Setup registry with RAGRegion needing defaults
        entry = RegionEntry(
            name="customer_support",
            type="RAGRegion",
            task="provide customer assistance",
            connections=[]
        )
        self.registry.regions = [entry]
        self.registry._update_names()

        # Build regions
        success = self.registry.build_regions()
        region = self.registry["customer_support"]

        self.assertTrue(success)
        self.assertEqual(region.rag, self.mock_rag)

        dir_path = os.path.dirname(__file__)
        os.remove(dir_path + "/rag_storage.db")

    async def test_update_region(self):
        """Test region configuration updates"""
        # Register initial region
        entry = RegionEntry(
            name="sales",
            type="MockRegion",
            task="handle sales inquiries",
            connections=[]
        )
        self.registry.register(entry)

        # Update task description
        updated_entry = RegionEntry(
            name="sales",
            type="MockRegion",
            task="handle updated sales inquiries",
            connections=[]
        )
        self.registry.update(updated_entry)

        self.assertEqual(self.registry["sales"].task, "handle updated sales inquiries")

if __name__ == '__main__':
    unittest.main()
