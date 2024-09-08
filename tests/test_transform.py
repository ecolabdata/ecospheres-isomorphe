from pathlib import Path

from conftest import Fixture

from ecospheres_migrator.batch import Batch
from ecospheres_migrator.geonetwork import Record
from ecospheres_migrator.migrator import Migrator


def get_transformation_path(name: str) -> Path:
    transformations = Migrator.list_transformations(Path("ecospheres_migrator/transformations"))
    transformation = next((t for t in transformations if t.name == name), None)
    if not transformation:
        raise ValueError(f"No transformation found with name {name}")
    return transformation.path


def get_transform_results(transformation: str, migrator: Migrator) -> tuple[Batch, list[Record]]:
    selection = migrator.select(query="type=dataset")
    assert len(selection) > 0
    return migrator.transform(get_transformation_path(transformation), selection), selection


def test_transform_noop(md_fixtures: list[Fixture], migrator: Migrator):
    results, selection = get_transform_results("noop", migrator)
    assert len(results.successes()) == len(selection)
    assert len(results.failures()) == 0


def test_transform_error(md_fixtures: list[Fixture], migrator: Migrator):
    results, selection = get_transform_results("error", migrator)
    assert len(results.successes()) == 0
    assert len(results.failures()) == len(selection)
