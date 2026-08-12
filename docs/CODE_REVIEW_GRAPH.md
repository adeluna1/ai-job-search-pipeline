# Code Review Graph integration

Code Review Graph is the code-quality layer for this repository. It maps functions, classes, imports, calls, communities, flows, and test relationships so reviewers can focus on the code affected by a change. It does not replace Paperclip or participate in job discovery, scoring, verification, or applications.

## Safety boundaries

- Version `2.3.7` runs from the ignored `tools/code-review-graph-runtime/` virtual environment.
- Graph state stays in the ignored `.code-review-graph/` directory.
- `.code-review-graphignore` excludes credentials, resumes, spreadsheets, application history, reports, logs, authenticated browser state, dependencies, and generated graph data.
- Cloud embeddings are not installed or enabled. Core builds and reviews run locally.
- The Codex MCP connection exposes graph build/query/review tools but excludes embedding, wiki-generation, refactor-preview, and refactor-application tools.
- Hooks and instruction injection are intentionally disabled. The pipeline's Paperclip agent instructions remain authoritative.
- The GitHub workflow is advisory: `fail-on-risk: none` means a graph finding cannot block a pull request.

## Install the isolated runtime

From the repository root in PowerShell:

```powershell
python -m venv tools\code-review-graph-runtime
.\tools\code-review-graph-runtime\Scripts\python.exe -m pip install "code-review-graph==2.3.7"
```

The runtime is machine-local and is not committed. To confirm the installed version:

```powershell
.\tools\code-review-graph-runtime\Scripts\code-review-graph.exe --version
```

## Common commands

The wrapper sets UTF-8 mode, resolves the repository root, and uses the isolated executable:

```powershell
# Build or refresh the structural graph
.\scripts\code-review-graph.cmd build
.\scripts\code-review-graph.cmd update

# Inspect graph health and review current changes
.\scripts\code-review-graph.cmd status
.\scripts\code-review-graph.cmd detect-changes --brief

# Generate an ignored, interactive local visualization
.\scripts\code-review-graph.cmd visualize
```

The visualization is written to `.code-review-graph/graph.html`. Do not commit that file because it can contain source-derived names and relationships.

## Codex MCP scope

The local Codex server is registered with `PYTHONUTF8=1`, an explicit repository path, and this allowlist:

```text
build_or_update_graph_tool,run_postprocess_tool,get_minimal_context_tool,
get_impact_radius_tool,query_graph_tool,get_review_context_tool,
list_graph_stats_tool,get_docs_section_tool,find_large_functions_tool,
list_flows_tool,get_flow_tool,get_affected_flows_tool,list_communities_tool,
get_community_tool,get_architecture_overview_tool,detect_changes_tool,
get_wiki_page_tool,get_hub_nodes_tool,get_bridge_nodes_tool,
get_knowledge_gaps_tool,get_surprising_connections_tool,
get_suggested_questions_tool,traverse_graph_tool
```

Restart Codex after initial MCP registration so the new server becomes available. The graph can still be built and reviewed through the wrapper without restarting.

## GitHub pull-request review

`.github/workflows/code-review-graph.yml` runs the upstream composite action on pull requests. It builds or restores a graph on the GitHub runner, posts one updated risk report, and never fails the job based on risk. The action receives only GitHub's scoped workflow token; no external AI key is configured.

For pull requests from forks, GitHub provides a read-only token. The workflow explicitly disables the comment for those runs, while the analysis remains visible in the Actions log. A privileged `pull_request_target` workflow is intentionally not used.
