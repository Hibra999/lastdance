$CondaHook = (& conda 'shell.powershell' 'hook') -join "`n"
Invoke-Expression $CondaHook
conda activate lastdance
