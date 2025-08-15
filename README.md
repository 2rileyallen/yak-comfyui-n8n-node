# n8n-nodes-yak-comfyui

This is an n8n community node. It lets you use ComfyUI in your n8n workflows.

ComfyUI is a modular, node-based AI image generation interface. This repository provides a performance-tuned local ComfyUI setup (including Sage Attention and ComfyUI-Manager) plus a custom n8n node for seamless automation.

[n8n](https://n8n.io/) is a [fair-code licensed](https://docs.n8n.io/reference/license/) workflow automation platform.

[Installation](#installation)  
[Operations](#operations)  
[Credentials](#credentials)  
[Compatibility](#compatibility)  
[Usage](#usage)  
[Resources](#resources)  
[Version history](#version-history)  

## Installation

Follow the [installation guide](https://docs.n8n.io/integrations/community-nodes/installation/) in the n8n community nodes documentation.

### Prerequisites

Before you begin on Windows, ensure the following are installed and available in your system PATH:

* **Git:** For cloning repositories
* **Python 3.11+:** System-level installation  
* **Miniconda or Anaconda:** For creating an isolated, stable environment

### One-Click Setup

Clone this repository to your desired location (for example, inside your `.n8n/custom` folder), then run the setup script.

```bash
# Clone the repository
git clone <URL_TO_YOUR_GITHUB_REPO>

# Go into the project directory
cd yak-comfyui-n8n-node

# Run the Windows setup
setup_windows.bat

## Gatekeeper service

This project includes a crucial middleware component called the “Gatekeeper” (`gatekeeper.py`). It runs alongside ComfyUI and is responsible for:

* Receiving job requests from the n8n node
* Managing the ComfyUI queue to prevent conflicts
* Monitoring job progress via WebSockets
* Storing job history in a local SQLite database
* Handling callbacks to n8n when a job is complete

## n8n UI Update (Dynamic Workflows)

This update adds a dynamic, workflow-driven UI to the Yak ComfyUI n8n node.

What changed
- Dynamic workflow discovery: The node scans the local `workflows/` folder and populates a “Workflow” dropdown automatically.
- Dynamic inputs per workflow: When a workflow is selected, the node renders its input fields from that workflow’s `ui_inputs.json`.
- Strict, no-fallback behavior: If a workflow or config is invalid/missing, the node surfaces a clear error instead of falling back to a default.
- Execution mapping: On run, the node loads `workflow.json`, applies user inputs based on `ui_inputs.json.mappings`, and sends the composed payload to the Gatekeeper.

Folder structure (per workflow)
- workflows/<workflow-slug>/
  - workflow.json        (ComfyUI graph + metadata)
  - ui_inputs.json       (n8n property definitions + mappings into the graph)
  - dependencies.json    (custom nodes/models; used by setup manager)

How to add a new workflow
1. Create a folder under `workflows/` using a short, kebab-case slug (e.g., `basic-image-generation/`).
2. Add the three files: `workflow.json`, `ui_inputs.json`, `dependencies.json`.
3. Restart n8n to reload dynamic input fields. The dropdown updates as soon as the folder exists, but input definitions are loaded at node startup.
4. In your n8n workflow, select the new workflow in the Yak ComfyUI node and fill in the generated fields.

Notes and tips
- Keep node IDs consistent: `ui_inputs.json.mappings[*].nodeId` must reference an ID present in `workflow.json.workflow`.
- Use correct types: Set `type` to `number` for numeric inputs (steps, cfg, width, height, etc.) to avoid string coercion.
- Batch handling: If you want the node’s “Batch Size” control to affect a graph node (e.g., `EmptyLatentImage.inputs.batch_size`), include a `batchSize` mapping to that path.
- Troubleshooting:
  - Empty dropdown: Ensure `workflows/` exists and each workflow folder contains a valid `workflow.json`.
  - Inputs not appearing: Restart n8n after adding or changing `ui_inputs.json`.
  - Mapping errors: Verify `mappings[*].path` exists under the target node’s `inputs`.

Setup manager (optional)
- The node UI and execution read directly from the filesystem and do not require the setup manager.
- Use `tools/setup_manager.py` separately to consolidate, install/update/remove custom nodes and download models defined in `dependencies.json` across all workflows.