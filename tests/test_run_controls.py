from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_workbench.agent_runtime import _apply_main_run_controls, create_thread, queue_run_control, revise_run_control
from research_workbench.db import connect, utc_now
from research_workbench.domain_agents import _apply_domain_run_controls
from research_workbench.service import initialize_project


class RunControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name) / "project"
        initialize_project(self.project, "controls")
        self.thread = create_thread(self.project, "thread")
        now = utc_now()
        with connect(self.project) as connection:
            connection.execute(
                "INSERT INTO goals(goal_id,thread_id,objective,status,created_at) VALUES ('G',?,'task','active',?)",
                (self.thread["thread_id"], now),
            )
            connection.execute(
                "INSERT INTO runs(run_id,thread_id,goal_id,status,model_snapshot_json,created_at,updated_at) VALUES ('R',?,'G','RUNNING','{}',?,?)",
                (self.thread["thread_id"], now, now),
            )
            connection.execute(
                "INSERT INTO domain_agent_sessions(session_id,plugin_name,agent_id,title,status,memory_json,created_at,updated_at) VALUES ('S','p','a','A','active','{}',?,?)",
                (now, now),
            )
            connection.execute(
                "INSERT INTO domain_agent_runs(run_id,session_id,main_thread_id,status,model_snapshot_json,created_at,updated_at) VALUES ('D','S',?,'RUNNING','{}',?,?)",
                (self.thread["thread_id"], now, now),
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_main_run_accepts_steering_then_stops_at_a_boundary(self) -> None:
        queue_run_control(self.project, "main", "steer", "先核对表头", thread_id=self.thread["thread_id"])
        observations = []
        self.assertEqual(_apply_main_run_controls(self.project, "R", observations), "steer")
        self.assertEqual(observations[0]["result"]["message"], "先核对表头")
        queue_run_control(self.project, "main", "stop", thread_id=self.thread["thread_id"])
        self.assertEqual(_apply_main_run_controls(self.project, "R", observations), "stop")
        with connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT status FROM runs WHERE run_id='R'").fetchone()[0], "STOPPED")

    def test_domain_run_uses_the_same_stop_control(self) -> None:
        queue_run_control(self.project, "domain", "stop", session_id="S")
        self.assertEqual(_apply_domain_run_controls(self.project, "D"), "stop")
        with connect(self.project) as connection:
            self.assertEqual(connection.execute("SELECT status FROM domain_agent_runs WHERE run_id='D'").fetchone()[0], "STOPPED")

    def test_queued_direction_can_be_edited_or_deleted_before_it_is_applied(self) -> None:
        queued = queue_run_control(self.project, "main", "steer", "旧方向", thread_id=self.thread["thread_id"])
        revise_run_control(self.project, queued["control_id"], content="新方向")
        with connect(self.project) as connection:
            payload = connection.execute(
                "SELECT content_json FROM messages WHERE json_extract(content_json,'$.run_control_id')=?",
                (queued["control_id"],),
            ).fetchone()[0]
        self.assertIn("新方向", payload)
        revise_run_control(self.project, queued["control_id"], delete=True)
        with connect(self.project) as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM agent_run_controls WHERE control_id=?", (queued["control_id"],)
            ).fetchone())


if __name__ == "__main__":
    unittest.main()
