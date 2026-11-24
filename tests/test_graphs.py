"""Unit tests for the CV generation and ingestion graph architectures."""
from unittest.mock import patch, MagicMock

from generation.graph import build_graph
from generation.nodes import node_refiner
from ingestion.graph import build_ingest_graph
from generation.state import CVPipelineState, RegionalStrategy
from ingestion.state import IngestionState


class TestGraphArchitectures:
    """Deterministic offline tests for StateGraph orchestrations."""

    def test_cv_refiner_guard_routing_overflow(self):
        """Test node_refiner routes to compressor when overflow feedback exists and cycles < 2."""
        state = CVPipelineState(
            draft_cv="word " * 2000, # forces overflow
            compression_count=0,
            strategy_metadata=RegionalStrategy(max_pages=1)
        )
        command = node_refiner(state)
        assert command.goto == "compressor"

    def test_cv_refiner_guard_routing_max_cycles(self):
        """Test node_refiner forces to auditor after 2 compression passes."""
        state = CVPipelineState(
            draft_cv="word " * 2000,
            compression_count=2,
            strategy_metadata=RegionalStrategy(max_pages=1)
        )
        command = node_refiner(state)
        assert command.goto == "auditor"

    def test_cv_refiner_guard_routing_within_budget(self):
        """Test node_refiner proceeds directly to auditor when within budget."""
        state = CVPipelineState(
            draft_cv="word " * 100,
            compression_count=0,
            strategy_metadata=RegionalStrategy(max_pages=1)
        )
        command = node_refiner(state)
        assert command.goto == "auditor"

    def test_build_cv_graph(self):
        """Test compile of build_graph."""
        graph = build_graph()
        assert graph is not None
        assert "analyzer" in graph.nodes
        assert "compressor" in graph.nodes
        assert "refiner" in graph.nodes
        assert "auditor" in graph.nodes
        assert "retriever" in graph.nodes
        assert "drafter" in graph.nodes
        assert "refiner" in graph.nodes
        assert "auditor" in graph.nodes

    def test_build_ingest_graph(self):
        """Test compile and edge structures of build_ingest_graph."""
        graph = build_ingest_graph(dry_run=True)
        assert graph is not None
        assert "parser" in graph.nodes
        assert "classifier" in graph.nodes
        assert "extractor" in graph.nodes
        assert "entity_resolver" in graph.nodes
        assert "generator" in graph.nodes
        assert "merger" in graph.nodes
        assert "validator" in graph.nodes
        assert "writer" in graph.nodes

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

        assert writer_node_func is not None
        state = IngestionState(doc_type="experience")
        writer_node_func(state)
        mock_node_writer.assert_called_once_with(state, dry_run=True)
