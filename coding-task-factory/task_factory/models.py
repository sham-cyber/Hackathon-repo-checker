from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    source: str
    commit: str


@dataclass(frozen=True)
class TaskSpec:
    family: str
    title: str
    scenario: str
    requirements: str
    patch: str
    test_source: str
    expected_failures: tuple[str, ...]
    variant: str = "default"
    variation_dimensions: tuple[str, ...] = ()
    target_symbols: tuple[str, ...] = ()


TASK_TEST_PATH = "plugins/fraudguard/task_factory_generated_test.go"
TARGET_MODULE_PATH = "plugins/fraudguard"
