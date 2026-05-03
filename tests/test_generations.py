"""Tests for generation tracking and validity computation in ProjectManager."""

from pathlib import Path

import pytest

from splatrix.project_manager import ProjectManager
from splatrix.protocol import Operation, StageState


@pytest.fixture
def pm(tmp_path):
    mgr = ProjectManager()
    mgr.new_project(project_dir=str(tmp_path / "proj"))
    return mgr


class TestGenerations:
    def test_new_project_all_no_data(self, pm):
        for op in Operation:
            assert pm.operation_validity(op) == StageState.NO_DATA

    def test_bump_generation_increments(self, pm):
        assert pm.get_generation(Operation.DATA) == 0
        gen = pm.bump_generation(Operation.DATA)
        assert gen == 1
        assert pm.get_generation(Operation.DATA) == 1

    def test_bump_records_input_gen(self, pm):
        pm.bump_generation(Operation.DATA)
        gen = pm.bump_generation(Operation.TRAINING)
        assert gen == 1
        input_gen = pm.get_input_gen(Operation.TRAINING)
        assert input_gen == {"data": 1}

    def test_data_completed_becomes_valid(self, pm):
        pm.bump_generation(Operation.DATA)
        assert pm.operation_validity(Operation.DATA) == StageState.VALID

    def test_training_valid_when_deps_match(self, pm):
        pm.bump_generation(Operation.DATA)       # data gen=1
        pm.bump_generation(Operation.TRAINING)    # training gen=1, input_gen={data:1}
        assert pm.operation_validity(Operation.TRAINING) == StageState.VALID

    def test_training_outdated_when_data_rebumped(self, pm):
        pm.bump_generation(Operation.DATA)       # data gen=1
        pm.bump_generation(Operation.TRAINING)    # training gen=1, input_gen={data:1}
        pm.bump_generation(Operation.DATA)       # data gen=2
        assert pm.operation_validity(Operation.TRAINING) == StageState.OUTDATED

    def test_transitive_outdated_propagation(self, pm):
        pm.bump_generation(Operation.DATA)       # data gen=1
        pm.bump_generation(Operation.TRAINING)    # training gen=1, input_gen={data:1}
        pm.bump_generation(Operation.EXPORT)      # export gen=1, input_gen={training:1}
        assert pm.operation_validity(Operation.EXPORT) == StageState.VALID

        pm.bump_generation(Operation.DATA)       # data gen=2
        # training is outdated because input_gen.data=1 != current 2
        assert pm.operation_validity(Operation.TRAINING) == StageState.OUTDATED
        # export is transitively outdated (depends on training which is outdated)
        assert pm.operation_validity(Operation.EXPORT) == StageState.OUTDATED

    def test_rerunning_training_fixes_training_but_not_export(self, pm):
        pm.bump_generation(Operation.DATA)       # gen=1
        pm.bump_generation(Operation.TRAINING)    # gen=1, input_gen={data:1}
        pm.bump_generation(Operation.EXPORT)      # gen=1, input_gen={training:1}
        pm.bump_generation(Operation.DATA)       # gen=2

        pm.bump_generation(Operation.TRAINING)    # gen=2, input_gen={data:2}
        assert pm.operation_validity(Operation.TRAINING) == StageState.VALID
        # export still outdated: input_gen.training=1 != current training gen=2
        assert pm.operation_validity(Operation.EXPORT) == StageState.OUTDATED

    def test_all_operation_states(self, pm):
        states = pm.all_operation_states()
        for op in Operation:
            assert states[op] == StageState.NO_DATA

        pm.bump_generation(Operation.DATA)
        states = pm.all_operation_states()
        assert states[Operation.DATA] == StageState.VALID
        assert states[Operation.TRAINING] == StageState.NO_DATA

    def test_current_depends_on(self, pm):
        pm.bump_generation(Operation.DATA)
        deps = pm.current_depends_on(Operation.TRAINING)
        assert deps == {"data": 1}

    def test_data_has_no_dependencies(self, pm):
        deps = pm.current_depends_on(Operation.DATA)
        assert deps == {}

    def test_bump_before_swap_crash_scenario(self, pm):
        """If gen is bumped but data not swapped, downstream sees OUTDATED."""
        pm.bump_generation(Operation.DATA)
        pm.bump_generation(Operation.TRAINING)  # input_gen={data:1}

        # Simulate crash: bump data gen but don't actually swap data
        pm.bump_generation(Operation.DATA)  # gen=2, but old data still on disk
        # Training is now outdated (input_gen.data=1 != 2)
        assert pm.operation_validity(Operation.TRAINING) == StageState.OUTDATED

    def test_save_and_reload_preserves_generations(self, pm):
        pm.bump_generation(Operation.DATA)
        pm.bump_generation(Operation.TRAINING)
        pm.save_project()
        proj_dir = str(pm.project_dir)
        pm.close()

        pm2 = ProjectManager()
        pm2.load_project(proj_dir)
        assert pm2.get_generation(Operation.DATA) == 1
        assert pm2.get_generation(Operation.TRAINING) == 1
        assert pm2.get_input_gen(Operation.TRAINING) == {"data": 1}
        assert pm2.operation_validity(Operation.TRAINING) == StageState.VALID
        pm2.close()
