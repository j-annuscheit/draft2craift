"""Default worker registration."""
from __future__ import annotations

from .registry import StepRegistry
from .workers.canvas import (
    collect_context as canvas_collect_context,
    draft_patch as canvas_draft_patch,
    preview_and_apply as canvas_preview_and_apply,
    understand_edit_goal as canvas_understand_edit_goal,
    validate_patch_constraints as canvas_validate_patch_constraints,
)
from .workers.chat import (
    classify_user_intent as chat_classify_user_intent,
    draft_answer_with_citations as chat_draft_answer_with_citations,
    emit_response as chat_emit_response,
    plan_retrieval as chat_plan_retrieval,
    quality_gate_citations as chat_quality_gate_citations,
    retrieve_candidates as chat_retrieve_candidates,
)
from .workers.control import (
    emit_result as control_emit_result,
    fail as control_fail,
    increment_int as control_increment_int,
    pick_next_claim as control_pick_next_claim,
)
from .workers.factcheck import (
    append_fact_row as factcheck_append_fact_row,
    decide_retry_or_finalize as factcheck_decide_retry_or_finalize,
    extract_missing_claims as factcheck_extract_missing_claims,
    plan_query as factcheck_plan_query,
    plan_query_regex as factcheck_plan_query_regex,
    rag_execute as factcheck_rag_execute,
    rag_execute_regex_only as factcheck_rag_execute_regex_only,
    verify_basic as factcheck_verify_basic,
    verify_hybrid as factcheck_verify_hybrid,
)
from .workers.maps import (
    check_structure as maps_check_structure,
    collect_context as maps_collect_context,
    draft_map_raw as maps_draft_map_raw,
    draft_subgraph as maps_draft_subgraph,
    emit_to_canvas as maps_emit_to_canvas,
    ensure_connected_graph as maps_ensure_connected_graph,
    expand_map_depth as maps_expand_map_depth,
    fix_graph as maps_fix_graph,
    ground_map_draft as maps_ground_map_draft,
    merge_subgraph as maps_merge_subgraph,
    parse_map_draft as maps_parse_map_draft,
    plan_expansion as maps_plan_expansion,
    plan_focus as maps_plan_focus,
    quality_gate as maps_quality_gate,
    rag_search_expand as maps_rag_search_expand,
    refine_nodes as maps_refine_nodes,
    resolve_mode_scope as maps_resolve_mode_scope,
    revise_map as maps_revise_map,
    validate_schema as maps_validate_schema,
    validate_semantics as maps_validate_semantics,
)
from .workers.maps.apply import (
    attach_child_nodes as map_attach_child_nodes,
    attach_gap_fill as map_attach_gap_fill,
    commit_candidate_tree as map_commit_candidate_tree,
    commit_initial_tree as map_commit_initial_tree,
    decide_continue_expansion as map_decide_continue_expansion,
    ensure_connected_tree as map_ensure_connected_tree,
    ensure_single_root as map_ensure_single_root,
    merge_semantic_duplicates as map_merge_semantic_duplicates,
    normalize_labels as map_normalize_labels,
    update_coverage as map_update_coverage,
)
from .workers.maps.frontier import (
    collect_frontier_evidence as map_collect_frontier_evidence,
    detect_coverage_gaps as map_detect_coverage_gaps,
    extract_local_candidates as map_extract_local_candidates,
    parse_child_nodes as map_parse_child_nodes,
    parse_gap_fill as map_parse_gap_fill,
    propose_child_nodes as map_propose_child_nodes,
    propose_gap_fill as map_propose_gap_fill,
    repair_child_nodes as map_repair_child_nodes,
    select_frontier_node as map_select_frontier_node,
    select_gap_target as map_select_gap_target,
)
from .workers.maps.render import (
    emit_result as map_emit_result,
    render_markdown as map_render_markdown,
)
from .workers.maps.seed import (
    choose_root_label as map_choose_root_label,
    extract_seed_concepts as map_extract_seed_concepts,
    parse_seed_enrichment as map_parse_seed_enrichment,
    propose_seed_enrichment as map_propose_seed_enrichment,
    seed_from_outline as map_seed_from_outline,
)
from .workers.maps.source import (
    collect_context as map_collect_context,
    extract_outline as map_extract_outline,
    normalize_context as map_normalize_context,
    resolve_request as map_resolve_request,
    score_focus_sections as map_score_focus_sections,
    segment_context as map_segment_context,
)
from .workers.maps.validate import (
    validate_candidate_tree as map_validate_candidate_tree,
    validate_child_nodes as map_validate_child_nodes,
    validate_final_tree as map_validate_final_tree,
    validate_gap_fill as map_validate_gap_fill,
    validate_seed_enrichment as map_validate_seed_enrichment,
)


def register_default_runners(registry: StepRegistry) -> StepRegistry:
    registry.register("control.pick_next_claim.v1", control_pick_next_claim.run)
    registry.register("control.increment_int.v1", control_increment_int.run)
    registry.register("control.emit_result.v1", control_emit_result.run)
    registry.register("control.fail.v1", control_fail.run)

    registry.register("factcheck.extract_missing_claims.v1", factcheck_extract_missing_claims.run)
    registry.register("factcheck.plan_query.v1", factcheck_plan_query.run)
    registry.register("factcheck.plan_query.regex.v1", factcheck_plan_query_regex.run)
    registry.register("rag.execute.v1", factcheck_rag_execute.run)
    registry.register("rag.execute.regex_only.v1", factcheck_rag_execute_regex_only.run)
    registry.register("factcheck.verify.v1", factcheck_verify_basic.run)
    registry.register("factcheck.verify.hybrid.v1", factcheck_verify_hybrid.run)
    registry.register("controller.retry_or_finalize.v1", factcheck_decide_retry_or_finalize.run)
    registry.register("factcheck.append_fact_row.v1", factcheck_append_fact_row.run)

    registry.register("chat.classify_user_intent.v1", chat_classify_user_intent.run)
    registry.register("chat.plan_retrieval.v1", chat_plan_retrieval.run)
    registry.register("chat.retrieve_candidates.v1", chat_retrieve_candidates.run)
    registry.register("chat.draft_answer_with_citations.v1", chat_draft_answer_with_citations.run)
    registry.register("chat.quality_gate.citations.v1", chat_quality_gate_citations.run)
    registry.register("chat.emit_response.v1", chat_emit_response.run)

    registry.register("canvas.understand_edit_goal.v1", canvas_understand_edit_goal.run)
    registry.register("canvas.collect_context.v1", canvas_collect_context.run)
    registry.register("canvas.draft_patch.v1", canvas_draft_patch.run)
    registry.register("canvas.validate_patch_constraints.v1", canvas_validate_patch_constraints.run)
    registry.register("canvas.preview_and_apply.v1", canvas_preview_and_apply.run)

    registry.register("mindmap.resolve_mode_scope.v1", maps_resolve_mode_scope.run)
    registry.register("mindmap.collect_context.v1", maps_collect_context.run)
    registry.register("mindmap.plan_focus.v1", maps_plan_focus.run)
    registry.register("mindmap.draft_map_raw.v1", maps_draft_map_raw.run)
    registry.register("mindmap.parse_map_draft.v1", maps_parse_map_draft.run)
    registry.register("mindmap.ground_map_draft.v1", maps_ground_map_draft.run)
    registry.register("mindmap.validate_schema.v1", maps_validate_schema.run)
    registry.register("mindmap.ensure_connected_graph.v1", maps_ensure_connected_graph.run)
    registry.register("mindmap.quality_gate.v1", maps_quality_gate.run)
    registry.register("mindmap.refine_nodes.v1", maps_refine_nodes.run)
    registry.register("mindmap.expand_map_depth.v1", maps_expand_map_depth.run)
    registry.register("mindmap.emit_to_canvas.v1", maps_emit_to_canvas.run)

    registry.register("mindmap.check_structure.v1", maps_check_structure.run)
    registry.register("mindmap.fix_graph.v1", maps_fix_graph.run)
    registry.register("mindmap.validate_semantics.v1", maps_validate_semantics.run)
    registry.register("mindmap.revise_map.v1", maps_revise_map.run)
    registry.register("mindmap.plan_expansion.v1", maps_plan_expansion.run)
    registry.register("mindmap.rag_search_expand.v1", maps_rag_search_expand.run)
    registry.register("mindmap.draft_subgraph.v1", maps_draft_subgraph.run)
    registry.register("mindmap.merge_subgraph.v1", maps_merge_subgraph.run)

    registry.register("map.resolve_request.v1", map_resolve_request.run)
    registry.register("map.collect_context.v1", map_collect_context.run)
    registry.register("map.normalize_context.v1", map_normalize_context.run)
    registry.register("map.segment_context.v1", map_segment_context.run)
    registry.register("map.extract_outline.v1", map_extract_outline.run)
    registry.register("map.score_focus_sections.v1", map_score_focus_sections.run)
    registry.register("map.choose_root_label.v1", map_choose_root_label.run)
    registry.register("map.seed_from_outline.v1", map_seed_from_outline.run)
    registry.register("map.extract_seed_concepts.v1", map_extract_seed_concepts.run)
    registry.register("map.propose_seed_enrichment.v1", map_propose_seed_enrichment.run)
    registry.register("map.parse_seed_enrichment.v1", map_parse_seed_enrichment.run)
    registry.register("map.validate_seed_enrichment.v1", map_validate_seed_enrichment.run)
    registry.register("map.commit_initial_tree.v1", map_commit_initial_tree.run)
    registry.register("map.select_frontier_node.v1", map_select_frontier_node.run)
    registry.register("map.collect_frontier_evidence.v1", map_collect_frontier_evidence.run)
    registry.register("map.extract_local_candidates.v1", map_extract_local_candidates.run)
    registry.register("map.propose_child_nodes.v1", map_propose_child_nodes.run)
    registry.register("map.parse_child_nodes.v1", map_parse_child_nodes.run)
    registry.register("map.repair_child_nodes.v1", map_repair_child_nodes.run)
    registry.register("map.validate_child_nodes.v1", map_validate_child_nodes.run)
    registry.register("map.attach_child_nodes.v1", map_attach_child_nodes.run)
    registry.register("map.detect_coverage_gaps.v1", map_detect_coverage_gaps.run)
    registry.register("map.select_gap_target.v1", map_select_gap_target.run)
    registry.register("map.propose_gap_fill.v1", map_propose_gap_fill.run)
    registry.register("map.parse_gap_fill.v1", map_parse_gap_fill.run)
    registry.register("map.validate_gap_fill.v1", map_validate_gap_fill.run)
    registry.register("map.attach_gap_fill.v1", map_attach_gap_fill.run)
    registry.register("map.validate_candidate_tree.v1", map_validate_candidate_tree.run)
    registry.register("map.commit_candidate_tree.v1", map_commit_candidate_tree.run)
    registry.register("map.update_coverage.v1", map_update_coverage.run)
    registry.register("map.decide_continue_expansion.v1", map_decide_continue_expansion.run)
    registry.register("map.normalize_labels.v1", map_normalize_labels.run)
    registry.register("map.merge_semantic_duplicates.v1", map_merge_semantic_duplicates.run)
    registry.register("map.ensure_single_root.v1", map_ensure_single_root.run)
    registry.register("map.ensure_connected_tree.v1", map_ensure_connected_tree.run)
    registry.register("map.validate_final_tree.v1", map_validate_final_tree.run)
    registry.register("map.render_markdown.v1", map_render_markdown.run)
    registry.register("map.emit_result.v1", map_emit_result.run)
    return registry
