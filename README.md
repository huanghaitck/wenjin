# Historical Research Workbench

Local-first, page-aware infrastructure for auditable historical research projects.

## Environment

The project uses its own Conda environment at
`D:\AI_Workflows\conda-envs\historical-research-workbench`. Recreate it with:

```powershell
conda env create --prefix D:\AI_Workflows\conda-envs\historical-research-workbench --file environment.yml
conda env config vars set --prefix D:\AI_Workflows\conda-envs\historical-research-workbench PYTHONNOUSERSITE=1
```

## Current status

`M2_PDF_INTAKE_AND_REPAIR_WORKBENCH_COMPLETE_AWAITING_M3_APPROVAL`

M1 provides the project state kernel. M2 adds:

- real PDF page rendering;
- coordinate-preserving text-layer extraction;
- page-aware Markdown artifacts;
- conservative page and cross-page quality gates;
- a local page/anomaly repair workbench.

M2 does not call OCR or language models, access external networks, translate documents, create
evidence, write manuscripts or package a desktop application.

## Run tests

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python scripts\assert_environment.py
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench python -m unittest discover -s tests -v
```

## CLI

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw --help
```

Register and process a PDF:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw add-source D:\research\my-project D:\books\source.pdf
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw ingest-pdf D:\research\my-project SOURCE_ID
```

Open the local repair workbench:

```powershell
conda run --prefix D:\AI_Workflows\conda-envs\historical-research-workbench hrw serve D:\research\my-project
```

Then open `http://127.0.0.1:8765`. The interface can also import a PDF directly. The server binds
to loopback only. CLI commands continue to emit JSON so a later Tauri bridge can call the same
application service.
