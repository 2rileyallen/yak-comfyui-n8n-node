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