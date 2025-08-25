import unittest
import pathlib

from modules.orchestrator import Orchestrator

class TestOrchestrator(unittest.TestCase):

    def setUp(self):
        # Basic configuration for testing
        self.basic_layer_config = [
            {'chain1': ['foo', 'bar'], 'chain2': ['baz']},
            {'chain3': ['qux']}
        ]
        self.basic_execution_config = [
            [('foo', 'make_questions'), ('bar', 'make_questions'), ('baz', 'make_answers')],
            [('qux', 'ponder_deeply')]
        ]
        self.basic_execution_order = [0, 1]

    def test_init_with_none(self):
        """Test initialization with None parameters"""
        orchestrator = Orchestrator(None, None, None)
        self.assertEqual(orchestrator.layer_config, [])
        self.assertEqual(orchestrator.execution_config, [])
        self.assertEqual(orchestrator.execution_order, [])

    def test_pad(self):
        """Test pad functionality extends configurations properly"""
        orchestrator = Orchestrator([{'chain1': ['foo']}], [], [])
        orchestrator.pad(3)

        self.assertEqual(len(orchestrator.layer_config), 3)
        self.assertEqual(len(orchestrator.execution_config), 3)
        self.assertIsInstance(orchestrator.layer_config[1], dict)
        self.assertEqual(orchestrator.execution_config[2], [])

    def test_region_layers(self):
        """Test region_layers identifies correct layer indices"""
        orchestrator = Orchestrator(
            [{'chain1': ['foo', 'bar']}, {'chain2': ['foo']}],
            [],
            []
        )

        self.assertEqual(orchestrator.region_layers('foo'), [0, 1])
        self.assertEqual(orchestrator.region_layers('bar'), [0])
        self.assertEqual(orchestrator.region_layers('qux'), [])

    def test_silent_layer_verification(self):
        """Test verify() handles silent layers (empty layer config but non-empty execution)"""
        orchestrator = Orchestrator(
            [{}],
            [[('foo', 'method')]],
            []
        )

        with self.assertLogs(level='WARNING') as log:
            result = orchestrator.verify()

        self.assertTrue(result)
        self.assertIn("empty layer configuration", log.output[0])

    def test_duplicate_regions_verification(self):
        """Test verify() detects duplicate regions within layers"""
        orchestrator = Orchestrator(
            [{'chain1': ['foo', 'foo']}],
            [[('foo', 'method')]],
            []
        )

        with self.assertLogs(level='ERROR') as log:
            result = orchestrator.verify()

        self.assertFalse(result)
        self.assertIn("duplicate regions", log.output[0])

    def test_append_to_layer(self):
        """Test append_to_layer edge cases"""
        orchestrator = Orchestrator([{'chain1': ['foo']}], [], [])

        # Append to new chain
        self.assertTrue(orchestrator.append_to_layer(0, 'chain2', 'bar'))
        self.assertEqual(orchestrator.layer_config[0]['chain2'], ['bar'])

        # Append existing region
        self.assertFalse(orchestrator.append_to_layer(0, 'chain3', 'foo'))

        # Append beyond current layers (triggers padding)
        self.assertTrue(orchestrator.append_to_layer(5, 'chain1', 'qux'))
        self.assertEqual(len(orchestrator.layer_config), 6)

    def test_remove_from_layer(self):
        """Test remove_from_layer handles removal and chain trimming"""
        orchestrator = Orchestrator(
            [{'chain1': ['foo', 'bar']}],
            [[('foo', 'method'), ('bar', 'method')]],
            []
        )

        # Remove existing region
        self.assertTrue(orchestrator.remove_from_layer(0, 'foo'))
        self.assertEqual(orchestrator.layer_config[0]['chain1'], ['bar'])

        # Remove last region from chain
        self.assertTrue(orchestrator.remove_from_layer(0, 'bar'))
        self.assertEqual(orchestrator.layer_config, [])

        # Remove non-existent region
        self.assertFalse(orchestrator.remove_from_layer(0, 'baz'))

    def test_region_profile(self):
        """Test region_profile correctly maps methods across layers"""
        orchestrator = Orchestrator(
            [],
            [
                [('foo', 'method1'), ('bar', 'method2')],
                [('foo', 'method3')]
            ],
            []
        )

        profile = orchestrator.region_profile('foo')
        self.assertEqual(profile, {0: ['method1'], 1: ['method3']})

        profile = orchestrator.region_profile('bar')
        self.assertEqual(profile, {0: ['method2']})

    def test_methods_in_layer(self):
        """Test methods_in_layer retrieves correct execution methods"""
        orchestrator = Orchestrator(
            [],
            [
                [('foo', 'method1'), ('foo', 'method2')],
                [('foo', 'method3')]
            ],
            []
        )

        self.assertEqual(orchestrator.methods_in_layer(0, 'foo'), ['method1', 'method2'])
        self.assertEqual(orchestrator.methods_in_layer(1, 'foo'), ['method3'])
        self.assertEqual(orchestrator.methods_in_layer(2, 'foo'), [])

    def test_execution_modification_methods(self):
        """Test remove_method, remove_methods, and replace_method"""
        orchestrator = Orchestrator(
            [],
            [
                [('foo', 'method1'), ('foo', 'method2')],
                [('bar', 'method3')]
            ],
            []
        )

        # Remove single method
        self.assertTrue(orchestrator.remove_method(0, 'foo', 'method1'))
        self.assertEqual(orchestrator.methods_in_layer(0, 'foo'), ['method2'])

        # Remove all methods
        self.assertEqual(orchestrator.remove_methods(0, 'foo'), 1)
        self.assertEqual(orchestrator.methods_in_layer(0, 'foo'), [])

        # Replace method
        self.assertTrue(orchestrator.replace_method(1, 'bar', 'method3', 'new_method'))
        self.assertEqual(orchestrator.methods_in_layer(1, 'bar'), ['new_method'])

    def test_save_load(self):
        """Test configuration serialization and deserialization"""
        orchestrator = Orchestrator(
            self.basic_layer_config,
            self.basic_execution_config,
            self.basic_execution_order
        )

        # Save to temporary file
        orchestrator.save('test_orchestrator.json')

        # Load back
        loaded = Orchestrator()
        try:
            self.assertTrue(loaded.load('test_orchestrator.json'))
            self.assertEqual(loaded.layer_config, self.basic_layer_config)
            self.assertEqual(loaded.execution_config, self.basic_execution_config)
            self.assertEqual(loaded.execution_order, self.basic_execution_order)
        finally:
            pathlib.Path('test_orchestrator.json').unlink()

    def test_verify_execution_order(self):
        """Test verify() validates execution_order indices"""
        orchestrator = Orchestrator(
            [{'chain1': ['foo']}],
            [[('foo', 'method')]],
            [2]  # Invalid index
        )

        with self.assertLogs(level='ERROR') as log:
            result = orchestrator.verify()

        self.assertFalse(result)
        self.assertIn("invalid layer index", log.output[0])

    def test_verify_missing_regions(self):
        """Test verify() checks regions with no execution methods"""
        orchestrator = Orchestrator(
            [{'chain1': ['foo']}],
            [],
            []
        )

        with self.assertLogs(level='WARNING') as log:
            result = orchestrator.verify()

        self.assertTrue(result)
        self.assertIn("has no execution methods", '\n'.join(log.output))