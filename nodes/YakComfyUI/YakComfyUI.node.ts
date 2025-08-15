import {
  IExecuteFunctions,
  ILoadOptionsFunctions,
  INodeExecutionData,
  INodeType,
  INodeTypeDescription,
  INodePropertyOptions,
  IHttpRequestOptions,
  NodeConnectionType,
  NodeOperationError,
  IDataObject,
} from 'n8n-workflow';
import WebSocket from 'ws';
import * as path from 'path';
import { promises as fs } from 'fs';

export class YakComfyUI implements INodeType {
  description: INodeTypeDescription = {
    displayName: 'Yak ComfyUI',
    name: 'yakComfyUi',
    group: ['transform'],
    version: 1,
    description: 'Triggers a workflow in a local ComfyUI instance via the Gatekeeper service.',
    defaults: {
      name: 'Yak ComfyUI',
    },
    inputs: [NodeConnectionType.Main],
    outputs: [NodeConnectionType.Main],
    properties: [
      // Workflow selection (dynamic via loadOptions)
      {
        displayName: 'Workflow',
        name: 'selectedWorkflow',
        type: 'options',
        typeOptions: {
          loadOptionsMethod: 'getWorkflows',
        },
        default: '',
        description: 'Select the ComfyUI workflow to execute.',
        required: true,
      },
      // Universal controls
      {
        displayName: 'Operation Mode',
        name: 'operationMode',
        type: 'options',
        options: [
          {
            name: 'Wait for Completion',
            value: 'websocket',
            description: 'The node will wait until the job is done and return the output.',
          },
          {
            name: 'Continue and Send to Webhook',
            value: 'webhook',
            description: 'The node finishes immediately and the result is sent to a webhook URL.',
          },
        ],
        default: 'websocket',
        description: 'Choose how the node should handle the job.',
      },
      {
        displayName: 'Webhook URL',
        name: 'webhookUrl',
        type: 'string',
        default: '',
        displayOptions: {
          show: {
            operationMode: ['webhook'],
          },
        },
        placeholder: 'https://your-n8n-instance/webhook-path',
        description: 'The URL to send the final result to.',
        required: true,
      },
      {
        displayName: 'Output Format',
        name: 'outputFormat',
        type: 'options',
        options: [
          { name: 'Binary Data', value: 'binary', description: 'Returns the output file (e.g., image, video) as binary data.' },
          { name: 'File Path', value: 'filePath', description: 'Returns the local file path to the output file.' },
          { name: 'Text', value: 'text', description: 'Returns a text-based output.' },
        ],
        default: 'binary',
        description: 'The desired format for the output.',
      },
      {
        displayName: 'Batch Size',
        name: 'batchSize',
        type: 'number',
        typeOptions: { minValue: 1 },
        default: 1,
        description: 'How many images to generate for each input item.',
      },
      // Dynamic workflow-specific properties are appended at runtime in the constructor
    ],
  };

  constructor() {
    // Preload and append dynamic properties from all workflows at node load time
    // No fallbacks; if this fails the UI won’t show inputs and execution will error out
    void this.loadAndAppendDynamicProperties();
  }

  // Resolve the root of this custom node package
  private getRepoRoot(): string {
    return path.join(__dirname, '..', '..', '..');
  }

  private getWorkflowsDir(): string {
    return path.join(this.getRepoRoot(), 'workflows');
  }

  private async pathExists(p: string): Promise<boolean> {
    try {
      await fs.access(p);
      return true;
    } catch {
      return false;
    }
  }

  private async readJson<T = any>(filePath: string): Promise<T> {
    const raw = await fs.readFile(filePath, 'utf-8');
    return JSON.parse(raw) as T;
  }

  methods = {
    loadOptions: {
      // Dynamically populate the Workflow dropdown by scanning the workflows directory
      async getWorkflows(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
        const repoRoot = path.join(__dirname, '..', '..', '..');
        const workflowsDir = path.join(repoRoot, 'workflows');

        // Ensure workflows folder exists
        try {
          await fs.access(workflowsDir);
        } catch {
          throw new NodeOperationError(
            this.getNode(),
            `Workflows directory not found at: ${workflowsDir}`,
          );
        }

        // List folders with a workflow.json file
        const entries = await fs.readdir(workflowsDir, { withFileTypes: true });
        const workflows: string[] = [];
        for (const entry of entries) {
          if (!entry.isDirectory()) continue;
          const wfPath = path.join(workflowsDir, entry.name, 'workflow.json');
          try {
            await fs.access(wfPath);
            workflows.push(entry.name);
          } catch {
            // skip
          }
        }

        if (workflows.length === 0) {
          throw new NodeOperationError(
            this.getNode(),
            'No workflows found. Ensure each workflow folder contains a workflow.json file.',
          );
        }

        return workflows.map((workflow) => ({
          name: workflow.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()),
          value: workflow,
          description: `Execute the ${workflow} workflow`,
        }));
      },
    },
  };

  // Load ui_inputs.properties for all workflows and append them as dynamic node properties with displayOptions
  private async loadAndAppendDynamicProperties() {
    try {
      const workflowsDir = this.getWorkflowsDir();

      if (!(await this.pathExists(workflowsDir))) {
        // No silent fallback; log only
        // eslint-disable-next-line no-console
        console.error(`Workflows directory does not exist: ${workflowsDir}`);
        return;
      }

      const entries = await fs.readdir(workflowsDir, { withFileTypes: true });
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;

        const wfName = entry.name;
        const uiInputsPath = path.join(workflowsDir, wfName, 'ui_inputs.json');

        if (!(await this.pathExists(uiInputsPath))) continue;

        try {
          const uiConfig = await this.readJson<{ properties?: any[] }>(uiInputsPath);
          const props = uiConfig?.properties ?? [];
          for (const prop of props) {
            // Ensure each dynamic property is only visible when this workflow is selected
            const dynamicProperty = {
              ...prop,
              displayOptions: {
                ...(prop.displayOptions ?? {}),
                show: {
                  ...(prop.displayOptions?.show ?? {}),
                  selectedWorkflow: [wfName],
                },
              },
            };
            this.description.properties.push(dynamicProperty);
          }
        } catch (e) {
          // eslint-disable-next-line no-console
          console.error(`Failed to read ui_inputs.json for workflow '${wfName}':`, (e as Error).message);
        }
      }
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('Failed to load dynamic properties:', (error as Error).message);
    }
  }

  // Utility: set deep property by dot-path (e.g., "inputs.text")
  private static setByPath(obj: any, pathStr: string, value: any) {
    const parts = pathStr.split('.');
    let ref = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      const key = parts[i];
      if (ref[key] === undefined || ref[key] === null) ref[key] = {};
      ref = ref[key];
    }
    ref[parts[parts.length - 1]] = value;
  }

  // Apply user input mappings into the workflow JSON
  private static applyUserInputsToWorkflow(
    workflow: any,
    userInputs: IDataObject,
    mappings: Record<string, { nodeId: string; path: string }>,
    batchSize: number,
  ): any {
    const modified = JSON.parse(JSON.stringify(workflow));

    for (const [inputName, mapping] of Object.entries(mappings || {})) {
      const { nodeId, path: pathStr } = mapping as { nodeId: string; path: string };
      if (!modified[nodeId]) continue;

      if (inputName === 'batchSize' && pathStr === 'inputs.batch_size') {
        YakComfyUI.setByPath(modified[nodeId], pathStr, batchSize);
        continue;
      }

      if (userInputs[inputName] !== undefined) {
        YakComfyUI.setByPath(modified[nodeId], pathStr, userInputs[inputName]);
      }
    }

    return modified;
  }

  async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
    const items = this.getInputData();
    const returnData: INodeExecutionData[] = [];

    // Helper to load the full workflow config from disk for the selected workflow
    const loadWorkflowConfigFromDisk = async (workflowName: string) => {
  		const repoRoot = path.join(__dirname, '..', '..', '..'); // compute repo root locally
  		const base = path.join(repoRoot, 'workflows', workflowName);
  		const workflowJsonPath = path.join(base, 'workflow.json');
  		const uiInputsPath = path.join(base, 'ui_inputs.json');

  		const readJson = async (p: string) => JSON.parse(await fs.readFile(p, 'utf-8'));

  		try {
    	  const [workflowFile, uiFile] = await Promise.all([
      		readJson(workflowJsonPath),
      		readJson(uiInputsPath),
    	  ]);
    	  return { workflow: workflowFile, ui_inputs: uiFile };
  		} catch (e) {
    	  throw new NodeOperationError(
      		this.getNode(),
      		`Failed to load config for workflow '${workflowName}': ${(e as Error).message}`,
    	  );
  		}
	};

    for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
      try {
        // Required params
        const selectedWorkflow = this.getNodeParameter('selectedWorkflow', itemIndex) as string;
        const operationMode = this.getNodeParameter('operationMode', itemIndex, 'websocket') as string;
        const outputFormat = this.getNodeParameter('outputFormat', itemIndex, 'binary') as string;
        const batchSize = this.getNodeParameter('batchSize', itemIndex, 1) as number;

        if (!selectedWorkflow) {
          throw new NodeOperationError(
            this.getNode(),
            'No workflow selected. Please select a workflow from the dropdown.',
          );
        }

        // Load config for selected workflow
        const workflowConfig = await loadWorkflowConfigFromDisk(selectedWorkflow);

        if (!workflowConfig || !workflowConfig.workflow || !workflowConfig.ui_inputs) {
          throw new NodeOperationError(
            this.getNode(),
            `Failed to load workflow configuration for '${selectedWorkflow}'. Check that workflow.json and ui_inputs.json exist.`,
          );
        }

        const workflowTemplate = workflowConfig.workflow.workflow;
        const mappings = (workflowConfig.ui_inputs.mappings || {}) as Record<
          string,
          { nodeId: string; path: string }
        >;

        // Gather dynamic inputs for this workflow
        const userInputs: IDataObject = {};
        const dynamicProperties = (workflowConfig.ui_inputs.properties || []) as Array<{
          name: string;
          default?: any;
        }>;

        for (const prop of dynamicProperties) {
          try {
            const value = this.getNodeParameter(prop.name, itemIndex, prop.default);
            userInputs[prop.name] = value;
          } catch {
            userInputs[prop.name] = prop.default ?? '';
          }
        }

        // Apply user inputs and batch size to the workflow
        const finalWorkflow = YakComfyUI.applyUserInputsToWorkflow(
          workflowTemplate,
          userInputs,
          mappings,
          batchSize,
        );

        // Send to gatekeeper
        const gatekeeperPayload: IDataObject = {
          n8n_execution_id: this.getExecutionId(),
          callback_type: operationMode,
          output_format: outputFormat,
          workflow_json: finalWorkflow,
        };

        if (operationMode === 'webhook') {
          gatekeeperPayload.callback_url = this.getNodeParameter('webhookUrl', itemIndex, '') as string;
        }

        const initialOptions: IHttpRequestOptions = {
          method: 'POST',
          url: 'http://127.0.0.1:8189/execute',
          body: gatekeeperPayload,
          json: true,
        };

        // Submit job
        const initialResponse = (await this.helpers.httpRequest(initialOptions)) as { job_id: string };
        const jobId = initialResponse.job_id;

        if (operationMode === 'webhook') {
          returnData.push({
            json: {
              status: 'submitted',
              job_id: jobId,
              workflow: selectedWorkflow,
            },
            pairedItem: { item: itemIndex },
          });
          continue;
        }

        // Wait via WebSocket for final result
        const finalResult = await new Promise<any>((resolve, reject) => {
          const ws = new WebSocket(`ws://127.0.0.1:8189/ws/${jobId}`);
          const timeout = setTimeout(() => {
            ws.close();
            reject(
              new NodeOperationError(
                this.getNode(),
                'Job timed out. No response from Gatekeeper WebSocket.',
              ),
            );
          }, 60000);

          ws.on('message', (data) => {
            clearTimeout(timeout);
            ws.close();
            try {
              resolve(JSON.parse(data.toString()));
            } catch {
              reject(
                new NodeOperationError(
                  this.getNode(),
                  'Failed to parse WebSocket message from Gatekeeper.',
                ),
              );
            }
          });

          ws.on('error', (err) => {
            clearTimeout(timeout);
            reject(new NodeOperationError(this.getNode(), `WebSocket connection error: ${err.message}`));
          });
        });

        // Process results
        if (finalResult.format === 'multiple' && finalResult.results) {
          for (const result of finalResult.results) {
            const output: INodeExecutionData = { json: {}, pairedItem: { item: itemIndex } };

            if (result.format === 'binary' && result.data) {
              const imageData = Buffer.from(result.data, 'base64');
              const mimeType = result.mime_type || 'image/png';
              const binaryData = await this.helpers.prepareBinaryData(imageData, result.filename, mimeType);
              output.binary = { data: binaryData };
            } else if (result.format === 'filePath' && result.data) {
              output.json.filePath = result.data;
              output.json.filename = result.filename;
              output.json.type = result.type;
            } else if (result.format === 'text' && result.data) {
              output.json.text = result.data;
            } else {
              output.json.error = 'Received an unexpected result format in batch.';
              output.json.rawResult = result;
            }

            returnData.push(output);
          }
        } else {
          const output: INodeExecutionData = { json: {}, pairedItem: { item: itemIndex } };

          if (finalResult.format === 'binary' && finalResult.data) {
            const imageData = Buffer.from(finalResult.data, 'base64');
            const mimeType = finalResult.mime_type || 'image/png';
            const binaryData = await this.helpers.prepareBinaryData(imageData, finalResult.filename, mimeType);
            output.binary = { data: binaryData };
          } else if (finalResult.format === 'filePath' && finalResult.data) {
            output.json.filePath = finalResult.data;
            output.json.filename = finalResult.filename;
            output.json.type = finalResult.type;
          } else if (finalResult.format === 'text' && finalResult.data) {
            output.json.text = finalResult.data;
          } else {
            output.json.error = 'Received an unexpected or empty result from the Gatekeeper.';
            output.json.rawResult = finalResult;
          }

          returnData.push(output);
        }
      } catch (error: any) {
        if (this.continueOnFail()) {
          returnData.push({ json: { error: error.message }, pairedItem: { item: itemIndex } });
          continue;
        }
        throw error;
      }
    }

    return [returnData];
  }
}