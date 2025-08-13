import asyncio
import os

def remove_db(name: str = 'example_rag.db'):
    """Remove a SQLite database file if it exists and has a .db extension.

    This function deletes a SQLite database file only if:
    1. The filename ends with the '.db' extension
    2. The file exists in the current directory

    Args:
        name: The name of the database file to remove (default: 'example_rag.db').
              Must end with '.db' extension to be processed.

    Behavior:
        - If name ends with '.db' and file exists: deletes the file and prints "Removed <name>"
        - If name ends with '.db' but file doesn't exist: prints "<name> not found"
        - If name doesn't end with '.db': prints "<name> is not a *.db file"
    """
    if name.endswith('.db'):
        if os.path.exists(name):
            os.remove(name)
            print("Removed " + name)
        else:
            print(name + " not found")
    else:
        print(name + ' is not a *.db file')

class TestSet:
    """Manages and executes a collection of async test functions with result reporting.

    Tracks test execution state, processes results, and provides formatted output for
    test suites. Supports both concurrent (gather) and sequential execution modes.

    Attributes:
        header (str): Custom header string displayed before test execution
        tests (list): List of async test functions/coroutines to execute
        test_names (list[str]): Human-readable names corresponding to each test
        results (list): Execution results (True for pass, False for failure)
        passed (int): Count of tests that passed
        total (int): Total number of tests to execute
    """
    def __init__(self, header: str = '=== Tests ===', tests: list = None, test_names: list[str] = None):
        """Initializes a new test suite configuration.

        Args:
            header (str, optional): Header text for test runs. Defaults to '=== Tests ==='.
            tests (list, optional): Async test functions to execute. Defaults to None.
            test_names (list[str], optional): Names corresponding to tests. Defaults to None.

        Raises:
            ValueError: If test_names length doesn't match tests length when both provided
        """
        self.header = header
        self.tests = tests
        self.test_names = test_names
        self.total = len(tests)
        if self.total != len(test_names):
            raise ValueError(f"{self.total} tests provided, but {len(test_names)} provided")
        self.results = []
        self.passed = 0
        self.results_bool = []

    def _new_run(self):
        """Resets internal state for a new test execution cycle.

        Clears previous results, resets passed count, and prints the header.
        Should be called before each test run to ensure clean state.
        """
        print(f"{self.header}\n")
        self.results = []
        self.results_bool = []
        self.passed = 0

    def _tally_result(self):
        for result in self.results:
            if result is True:
                self.results_bool.append(True)
            else:
                self.results_bool.append(False)
        self.passed = sum(self.results_bool)

    async def run_gather(self):
        """Executes all tests concurrently using asyncio.gather.

            Runs tests in parallel, capturing results/exceptions. Automatically handles
            state reset via _new_run() before execution.

            Returns:
                list: Results where True indicates success, False indicate failures

            Example:
                >>> await test_set.run_gather()
                === Tests ===

                (execution output)
        """
        self._new_run()
        try:
            self.results = await asyncio.gather(*self.tests, return_exceptions=True)
        except Exception as e:
            print(f"Error: {e}")
        self._tally_result()


    async def run_sequential(self):
        """Executes tests sequentially in the order they appear in the test list.

            Processes each test one after another, capturing results/exceptions.
            Automatically handles state reset via _new_run() before execution.

            Returns:
                list: Results where True indicates success, False indicate failures

            Example:
                >>> await test_set.run_sequential()
                === Tests ===

                (execution output)
        """
        self._new_run()
        for test in self.tests:
            try:
                self.results.append(await test)
            except Exception as e:
                self.results.append(e)
                print(f"✗ {str(type(e))[8:-2]}: {e}")
        self._tally_result()

    def result(self) -> tuple[int, int]:
        """Generates and prints detailed test execution report.

            Displays pass/fail status for each test with error details if applicable.
            Returns pass/fail counts and prints comprehensive results summary.

            Returns:
                tuple[int, int]: (passed_count, failed_count)

            Example:
                >>> test_set.result()
                === Results ===
                Passed: 3/4

                ✓ PASS: test_login
                ✓ PASS: test_logout
                ✗ FAIL: test_payment
                Error: TimeoutError('Payment gateway timeout')
                ✓ PASS: test_profile

                ⚠️ 1 tests failed.

            (3, 1)
        """
        print(f"\n=== Results ===")
        print(f"Passed: {self.passed}/{self.total}")

        for i, (name, result) in enumerate(zip(self.test_names, self.results)):
            status = "✓ PASS" if result is True else "✗ FAIL"
            print(f"  {status}: {name}")
            if result is not True and result is not False:
                print(f"    {str(type(result))[8:-2]}: {result}")

        if self.passed == self.total:
            print("\n✓ All tests passed!")

        else:
            print(f"\n⚠️ {self.total - self.passed} tests failed.")

        return self.passed, self.total - self.passed