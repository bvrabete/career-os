"""Unit tests for the CV generation and ingestion graph architectures."""
import unittest
from unittest.mock import patch, MagicMock
from langgraph.graph import END

from generation.graph import routing_logic, build_graph
from ingestion.graph import build_ingest_graph
from generation.state import CVPipelineState
from ingestion.state import IngestionState


class TestGraphArchitectures(unittest.TestCase):
    """Deterministic offline tests for StateGraph orchestrations."""

    def test_cv_routing_logic_refiner_feedback(self):
        """Test cv routing_logic returns drafter when refiner feedback exists and iterations < 3."""
        state = CVPipelineState(
            audit_feedback="PASS",
            refiner_feedback="Make it denser.",
            iteration_count=1
        )
        self.assertEqual(routing_logic(state), "drafter")

    def test_cv_routing_logic_refiner_feedback_limit(self):
        """Test cv routing_logic ends when iterations reach 3 even with refiner feedback."""
        state = CVPipelineState(
            audit_feedback="PASS",
            refiner_feedback="Make it denser.",
            iteration_count=3
        )
        self.assertEqual(routing_logic(state), str(END))

    def test_cv_routing_logic_pass(self):
        """Test cv routing_logic ends when auditor feedback contains PASS."""
        state = CVPipelineState(
            audit_feedback="Everything looks great, PASS.",
            refiner_feedback="",
            iteration_count=1
        )
        self.assertEqual(routing_logic(state), str(END))

    def test_cv_routing_logic_fail(self):
        """Test cv routing_logic re-drafts on audit failure."""
        state = CVPipelineState(
            audit_feedback="Too long, fix experience block.",
            refiner_feedback="",
            iteration_count=1
        )
        self.assertEqual(routing_logic(state), "drafter")

    def test_build_cv_graph(self):
        """Test compile of build_graph."""
        graph = build_graph()
        self.assertIsNotNone(graph)
        self.assertIn("analyzer", graph.nodes)
        self.assertIn("retriever", graph.nodes)
        self.assertIn("drafter", graph.nodes)
        self.assertIn("refiner", graph.nodes)
        self.assertIn("auditor", graph.nodes)

    def test_build_ingest_graph(self):
        """Test compile and edge structures of build_ingest_graph."""
        graph = build_ingest_graph(dry_run=True)
        self.assertIsNotNone(graph)
        self.assertIn("parser", graph.nodes)
        self.assertIn("classifier", graph.nodes)
        self.assertIn("extractor", graph.nodes)
        self.assertIn("entity_resolver", graph.nodes)
        self.assertIn("generator", graph.nodes)
        self.assertIn("merger", graph.nodes)
        self.assertIn("validator", graph.nodes)
        self.assertIn("writer", graph.nodes)

    @patch("ingestion.graph.StateGraph")
    @patch("ingestion.graph.node_writer")
    def test_build_ingest_graph_writer_node_execution(self, mock_node_writer, mock_state_graph):
        """Test that the custom writer node in ingest graph invokes node_writer."""
        mock_workflow = MagicMock()
        mock_state_graph.return_value = mock_workflow

        build_ingest_graph(dry_run=True)

        # Retrieve the nested writer_node function passed to add_node
        writer_node_func = None
        for call in mock_workflow.add_node.call_args_list:
            args, _ = call
            if args[0] == "writer":
                writer_node_func = args[1]
                break

        self.assertIsNotNone(writer_node_func)
        state = IngestionState(doc_type="experience")
        writer_node_func(state)
        mock_node_writer.assert_called_once_with(state, dry_run=True)


if __name__ == "__main__":
    unittest.main()
