# Workflows

当前 GPU 部署默认使用 worker 镜像内的官方 ComfyUI-LTXVideo workflow：

```text
/opt/comfyui/custom_nodes/ComfyUI-LTXVideo/example_workflows/2.3/LTX-2.3_T2V_I2V_Single_Stage_Distilled_Full.json
```

该路径由 `WORKFLOW_PATH` 配置。只有在需要固定一份经过人工确认的 Workflow API JSON 时，才把文件放到本目录，并在 `.env` 中把 `WORKFLOW_PATH` 指向挂载后的路径。

约束：

- 运行时消费 Workflow API Format JSON。
- 不把 ComfyUI 原生界面暴露为外部入口。
- 输入图片预处理由 control plane 下发的 `workflow_input_contract` 决定，worker adapter 执行，不在 workflow 文件里写业务状态逻辑。
