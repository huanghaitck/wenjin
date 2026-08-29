!macro NSIS_HOOK_PREINSTALL
  nsExec::ExecToLog 'taskkill /IM historical-research-workbench.exe /T /F'
  nsExec::ExecToLog 'taskkill /IM hrw-sidecar.exe /T /F'
  Sleep 1000
!macroend
