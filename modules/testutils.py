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
    """Manages and executes collections of async test functions with comprehensive result reporting.

    Tracks test execution state, processes results (including exceptions), and provides formatted output
    for test suites. Supports both concurrent (`run_gather`) and sequential (`run_sequential`) execution modes.
    Designed for integration with async test frameworks where tests return `True` on success or raise exceptions/
    return `False` on failure.

    Key Features:
    - Automatic state reset before each test run
    - Detailed pass/fail reporting with error diagnostics
    - Concurrent execution via `asyncio.gather`
    - Sequential execution for debugging or dependency-sensitive tests
    - Human-readable test naming for clear results

    Attributes:
        header (str): Custom header displayed before test execution (default: '=== Tests ===')
        tests (list): Async test coroutines to execute (must be non-None list)
        test_names (list[str]): Human-readable names for tests (must match `tests` length)
        results (list): Raw execution results (True, False, or exception objects)
        results_bool (list[bool]): Boolean pass/fail status (True=pass, False=fail)
        passed (int): Count of passing tests
        total (int): Total number of tests
    """

    def __init__(self, header: str = '=== Tests ===', tests: list = None, test_names: list[str] = None):
        """Initializes a test suite configuration.

        Args:
            header (str, optional): Header text for test runs. Defaults to '=== Tests ==='.
            tests (list): Async test coroutines to execute. **Must be provided as a non-None list**.
            test_names (list[str]): Human-readable names for tests. **Must be provided as a non-None list**
                matching the length of `tests`.

        Raises:
            ValueError: If `tests` and `test_names` lengths differ (e.g., 4 tests but 3 names)
            TypeError: If `tests` is None (required parameter)

        Note:
            Both `tests` and `test_names` are **required parameters** (despite default=None in signature).
            The class does not handle `None` values for these arguments. Ensure:
            - `tests` is a list of async coroutines
            - `test_names` is a list of strings with identical length to `tests`

        Example:
            >>> test_set = TestSet(
            ...     tests=[test_login, test_logout],
            ...     test_names=["User login", "User logout"]
            ... )
        """
        if tests is None:
            raise TypeError("tests must be a non-None list")
        if test_names is None:
            raise TypeError("test_names must be a non-None list")

        self.header = header
        self.tests = tests
        self.test_names = test_names
        self.total = len(tests)

        if self.total != len(test_names):
            raise ValueError(
                f"Length mismatch: {self.total} tests but {len(test_names)} names"
            )

        self.results = []
        self.results_bool = []
        self.passed = 0

    def _new_run(self):
        """Resets internal state for a new test execution cycle.

        Clears previous results, resets pass count, and prints the header. Automatically called
        before test execution in `run_gather`/`run_sequential`.

        Note:
            Internal method - not intended for direct use by consumers.

        Example:
            >>> test_set._new_run()
            === Tests ===

            (resets state)
        """
        print(f"{self.header}\n")
        self.results = []
        self.results_bool = []
        self.passed = 0

    def _tally_result(self):
        """Converts raw results into boolean pass/fail status and tallies successes.

        Processes `self.results` to:
        - Mark `True` results as passes
        - Mark `False` results or exceptions as fails
        - Update `self.passed` count

        Note:
            Internal method - not intended for direct use by consumers.

        Example:
            >>> test_set.results = [True, TimeoutError("Timeout"), False]
            >>> test_set._tally_result()
            # Sets results_bool = [True, False, False], passed = 1
        """
        self.results_bool = [result is True for result in self.results]
        self.passed = sum(self.results_bool)

    async def run_gather(self):
        """Executes all tests concurrently using asyncio.gather.

        Runs tests in parallel, capturing results/exceptions. Automatically:
        1. Resets state via `_new_run()`
        2. Executes tests with `asyncio.gather(return_exceptions=True)`
        3. Tallies results via `_tally_result()`

        Note:
            - **Does not return results** (results stored internally in `self.results`)
            - Exceptions are captured as objects in `results` (not raised)

        Example:
            >>> await test_set.run_gather()
            === Tests ===

            (concurrent execution output)
        """
        self._new_run()
        self.results = await asyncio.gather(*self.tests, return_exceptions=True)
        self._tally_result()

    async def run_sequential(self):
        """Executes tests sequentially in order.

        Processes tests one-by-one, capturing results/exceptions. Automatically:
        1. Resets state via `_new_run()`
        2. Executes each test sequentially
        3. Tallies results via `_tally_result()`

        Note:
            - **Does not return results** (results stored internally in `self.results`)
            - Exceptions are captured as objects in `results` (not raised)
            - Useful for debugging or tests with dependencies

        Example:
            >>> await test_set.run_sequential()
            === Tests ===

            (sequential execution output)
        """
        self._new_run()
        for test in self.tests:
            try:
                self.results.append(await test)
            except Exception as e:
                self.results.append(e)
        self._tally_result()

    def result(self) -> tuple[int, int]:
        """Generates and prints a detailed test execution report.

        Displays:
        - Pass/fail status per test with human-readable names
        - Error details for failed tests (exception type + message)
        - Summary of total passes/failures

        Returns:
            tuple[int, int]: (passed_count, failed_count)

        Example:
            >>> test_set.result()
            === Results ===
            Passed: 3/4

              ✓ PASS: User login
              ✓ PASS: User logout
              ✗ FAIL: Payment processing
                TimeoutError: Payment gateway timeout
              ✓ PASS: Profile update

            ⚠️ 1 tests failed

            (3, 1)

        Notes:
            - Tests returning `False` are marked as FAIL without error details
            - Exception-based failures show exception type and message
            - Prints "All tests passed!" if no failures
        """
        print(f"\n=== Results ===")
        print(f"Passed: {self.passed}/{self.total}")

        for i, (name, result) in enumerate(zip(self.test_names, self.results)):
            status = "✓ PASS" if result is True else "✗ FAIL"
            print(f"  {status}: {name}")

            # Show error details for exception-based failures
            if not isinstance(result, bool) and result is not True:
                # Extract exception type (e.g., "TimeoutError" from "<class 'TimeoutError'>")
                exc_type = str(type(result))[8:-2]
                print(f"    {exc_type}: {result}")

        if self.passed == self.total:
            print("\n✓ All tests passed!")
        else:
            print(f"\n⚠️ {self.total - self.passed} tests failed.")

        return self.passed, self.total - self.passed