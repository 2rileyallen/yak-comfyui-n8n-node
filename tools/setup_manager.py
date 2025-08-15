import os
import json
import subprocess
import requests
import gdown
from pathlib import Path
from typing import Dict, List, Any, Set
import shutil

class WorkflowSetupManager:
    def __init__(self, tools_dir: str = None):
        # Determine paths relative to this file location
        if tools_dir is None:
            tools_dir = Path(__file__).parent
        else:
            tools_dir = Path(tools_dir)
            
        self.tools_dir = tools_dir
        self.root_dir = tools_dir.parent  # One level up from tools/
        self.workflows_dir = self.root_dir / "workflows"
        self.comfyui_dir = self.root_dir / "ComfyUI"  # Adjust if different
        self.custom_nodes_dir = self.comfyui_dir / "custom_nodes"
        self.models_dir = self.comfyui_dir / "models"
        
    def scan_workflows(self) -> List[str]:
        """Get list of available workflow folders."""
        if not self.workflows_dir.exists():
            return []
        
        workflows = []
        for item in self.workflows_dir.iterdir():
            if item.is_dir() and (item / "workflow.json").exists():
                workflows.append(item.name)
        return workflows
    
    def load_workflow_config(self, workflow_name: str) -> Dict[str, Any]:
        """Load complete workflow configuration."""
        workflow_path = self.workflows_dir / workflow_name
        
        config = {}
        for file_name in ["workflow.json", "ui_inputs.json", "dependencies.json"]:
            file_path = workflow_path / file_name
            if file_path.exists():
                with open(file_path, 'r') as f:
                    config[file_name.replace('.json', '')] = json.load(f)
        
        return config
    
    def get_all_dependencies(self) -> Dict[str, List[Dict]]:
        """Consolidate dependencies from all workflows."""
        all_custom_nodes = []
        all_models = []
        
        for workflow_name in self.scan_workflows():
            config = self.load_workflow_config(workflow_name)
            deps = config.get('dependencies', {})
            
            all_custom_nodes.extend(deps.get('custom_nodes', []))
            all_models.extend(deps.get('models', []))
        
        # Remove duplicates by name
        unique_nodes = {node['name']: node for node in all_custom_nodes}.values()
        unique_models = {model['name']: model for model in all_models}.values()
        
        return {
            'custom_nodes': list(unique_nodes),
            'models': list(unique_models)
        }
    
    def get_installed_custom_nodes(self) -> Set[str]:
        """Get list of currently installed custom node folders."""
        if not self.custom_nodes_dir.exists():
            return set()
        
        installed = set()
        for item in self.custom_nodes_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                installed.add(item.name)
        return installed
    
    def install_custom_node(self, node_info: Dict[str, Any]) -> bool:
        """Install or update a single custom node."""
        try:
            repo_url = node_info.get('repo', '')
            node_name = node_info.get('name', '')
            
            if not repo_url or not node_name:
                print(f"Invalid node info: {node_info}")
                return False
            
            node_path = self.custom_nodes_dir / node_name
            
            if node_path.exists():
                print(f"Updating custom node: {node_name}")
                # Update existing node
                result = subprocess.run(
                    ['git', 'pull'], 
                    cwd=node_path, 
                    capture_output=True, 
                    text=True
                )
                print(f"Update result: {result.stdout}")
            else:
                print(f"Installing custom node: {node_name}")
                # Clone new node
                result = subprocess.run(
                    ['git', 'clone', repo_url, str(node_path)],
                    capture_output=True,
                    text=True
                )
                print(f"Install result: {result.stdout}")
            
            # Install requirements if they exist
            requirements_file = node_path / "requirements.txt"
            if requirements_file.exists():
                print(f"Installing requirements for {node_name}")
                subprocess.run([
                    'pip', 'install', '-r', str(requirements_file)
                ], capture_output=True)
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"Error installing custom node {node_name}: {str(e)}")
            return False
    
    def download_model_from_gdrive(self, model_info: Dict[str, Any]) -> bool:
        """Download model from Google Drive URL."""
        try:
            url = model_info.get('google_download_url', '')
            name = model_info.get('name', '')
            install_path = model_info.get('install_path', '')
            
            if not url or not name or not install_path:
                print(f"Invalid model info: {model_info}")
                return False
            
            # Create full install path
            full_install_path = self.models_dir / install_path.strip('/')
            full_install_path.mkdir(parents=True, exist_ok=True)
            
            # Full file path
            file_path = full_install_path / name
            
            # Skip if already exists
            if file_path.exists():
                print(f"Model {name} already exists, skipping download")
                return True
            
            print(f"Downloading model: {name}")
            print(f"From: {url}")
            print(f"To: {file_path}")
            
            # Use gdown for Google Drive downloads
            gdown.download(url, str(file_path), quiet=False, fuzzy=True)
            
            return file_path.exists()
            
        except Exception as e:
            print(f"Error downloading model {name}: {str(e)}")
            return False
    
    def manage_all_custom_nodes(self) -> Dict[str, Any]:
        """Install/update required nodes and remove unused ones."""
        required_nodes = self.get_all_dependencies()['custom_nodes']
        installed_nodes = self.get_installed_custom_nodes()
        
        required_node_names = {node['name'] for node in required_nodes}
        
        results = {
            'installed': [],
            'updated': [],
            'removed': [],
            'failed': []
        }
        
        # Install/update required nodes
        for node in required_nodes:
            node_name = node['name']
            if node_name in installed_nodes:
                if self.install_custom_node(node):
                    results['updated'].append(node_name)
                else:
                    results['failed'].append(node_name)
            else:
                if self.install_custom_node(node):
                    results['installed'].append(node_name)
                else:
                    results['failed'].append(node_name)
        
        # Remove unused nodes
        unused_nodes = installed_nodes - required_node_names
        for node_name in unused_nodes:
            try:
                node_path = self.custom_nodes_dir / node_name
                shutil.rmtree(node_path)
                results['removed'].append(node_name)
                print(f"Removed unused custom node: {node_name}")
            except Exception as e:
                print(f"Failed to remove {node_name}: {str(e)}")
        
        return results
    
    def download_all_models(self) -> Dict[str, Any]:
        """Download all required models."""
        required_models = self.get_all_dependencies()['models']
        
        results = {
            'downloaded': [],
            'skipped': [],
            'failed': []
        }
        
        for model in required_models:
            model_name = model['name']
            if model.get('google_download_url'):
                if self.download_model_from_gdrive(model):
                    if (self.models_dir / model.get('install_path', '') / model_name).exists():
                        results['downloaded'].append(model_name)
                    else:
                        results['skipped'].append(model_name)
                else:
                    results['failed'].append(model_name)
            else:
                print(f"No download URL for model: {model_name}")
                results['skipped'].append(model_name)
        
        return results
    
    def setup_all_dependencies(self) -> Dict[str, Any]:
        """Setup all dependencies (custom nodes + models)."""
        print("Setting up all workflow dependencies...")
        
        # Install/update custom nodes
        print("\n=== Managing Custom Nodes ===")
        node_results = self.manage_all_custom_nodes()
        
        # Download models
        print("\n=== Downloading Models ===")
        model_results = self.download_all_models()
        
        return {
            'custom_nodes': node_results,
            'models': model_results
        }
    
    def generate_dependency_report(self) -> str:
        """Generate a human-readable dependency report."""
        deps = self.get_all_dependencies()
        workflows = self.scan_workflows()
        
        report = f"=== YakComfyUI Dependency Report ===\n"
        report += f"Available Workflows: {len(workflows)}\n"
        report += f"Required Custom Nodes: {len(deps['custom_nodes'])}\n"
        report += f"Required Models: {len(deps['models'])}\n\n"
        
        report += "Workflows:\n"
        for workflow in workflows:
            report += f"  - {workflow}\n"
        
        report += "\nCustom Nodes:\n"
        for node in deps['custom_nodes']:
            report += f"  - {node['name']}\n"
        
        report += "\nModels:\n"
        for model in deps['models']:
            size_info = f" ({model.get('install_path', 'unknown path')})"
            report += f"  - {model['name']}{size_info}\n"
        
        return report

if __name__ == "__main__":
    manager = WorkflowSetupManager()
    
    print("YakComfyUI Setup Manager")
    print("========================")
    
    # Generate report
    print(manager.generate_dependency_report())
    
    # Optionally run full setup
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        results = manager.setup_all_dependencies()
        print("\nSetup Results:")
        print(json.dumps(results, indent=2))