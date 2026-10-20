# SearchBrief ComfyUI post-image template

This is a beginner-friendly, local text-to-image workflow for making an editorial illustration to accompany a SearchBrief post. It uses the installed `DreamShaper_8_pruned.safetensors` checkpoint, makes a 512 × 512 image in 12 steps to fit the Radeon 7600M's 8 GB VRAM more comfortably, and asks for no text or logos so the image does not invent poster copy. It does not verify the factual claims in a post.

## Open it in ComfyUI

1. Start ComfyUI and open `http://127.0.0.1:8188`.
2. Refresh ComfyUI once, open **Workflows**, and select **SearchBrief Post Image**. I also copied the visual workflow into ComfyUI's own `user/default/workflows/` folder so it is available there. You can also load the project copy `searchbrief_post_image_workflow.json` (or drag it into the page).
3. In the purple **Positive prompt · edit this** node, replace `[DESCRIBE THE IDEA HERE]` with one concrete visual idea. For example: `a small team carefully inspecting a complex transparent machine, representing human review of AI analysis`.
4. Optionally change the negative prompt. Keep it short and visual; don't put facts or article copy in the image prompt.
5. Click **Queue / Run**. The first run may take time while the checkpoint loads. The image appears in the preview and is saved under ComfyUI's `output/SearchBrief/` folder.
6. Review the image, then use it in SearchBrief only if it fits the post. Avoid implying that generated imagery is documentary evidence.

## Use it from SearchBrief

SearchBrief ships with the API workflow as its starter preset, so no workflow JSON needs to be pasted for the usual setup. Open **AI & Integrations → Image generation providers** and choose **ComfyUI · local** (the default for a new browser profile). The address is `http://127.0.0.1:8188`, and positive prompt node `2` is preconfigured. If you edited the workflow settings, use **Restore SearchBrief starter workflow** to reset them.

Start ComfyUI in the background, then open a draft's **Choose a visual → Generate new**, write a specific visual prompt, and select ComfyUI if another provider is selected. SearchBrief replaces node `2`'s text with your prompt, submits the workflow, and shows a preview. Review it before choosing **Use this image**. You do not need to open ComfyUI's web interface or node editor during normal use.

## Adjustments

- For more detail, increase width and height in the **Empty Latent Image** node gradually; larger images use more VRAM. The starter preset stays at `512 × 512` for the 8 GB GPU.
- To try the other installed checkpoint, change `DreamShaper_8_pruned.safetensors` to `Realistic_Vision_V5.1_fp16-no-ema.safetensors` in the Load Checkpoint node (API node `1`). The two checkpoints have different visual styles; preview before settling on one.
- The default launcher stops if its GPU preflight fails. CPU mode remains an explicit slower fallback via `run_comfyui_rocm62.sh --cpu`.

## If generation fails with `HIP error: invalid device function`

This message is not caused by the prompt text or the workflow links. The original PyTorch `2.5.1+rocm6.2` build lacked the GPU's native `gfx1102` target, and spoofing it as `gfx1100` still failed a basic GPU text-embedding operation. A separate ROCm 10.1 / PyTorch 2.13 environment is now installed at `tools/comfyui/venv-rocm101/`; its native `gfx1102` embedding test passed. The default launcher now uses it:

```bash
bash "/media/muhamadridhomm/Folder_Files/Steam/SSHIM Expanded/SSHIM Expanded Development/tools/comfyui/run_comfyui.sh"
```

The previous `venv/` remains intact, and its original launcher is preserved as `run_comfyui_rocm62.sh` for rollback. The new default launcher uses native gfx1102, performs a GPU embedding preflight, and binds only to localhost. If the GPU preflight fails, the launcher stops with an error instead of silently switching to slow CPU mode; use the old environment with `--cpu` only as a temporary fallback.
