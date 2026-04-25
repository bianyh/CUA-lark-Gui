$ErrorActionPreference = "Stop"

Write-Host "Python:"
python --version
where.exe python

Write-Host "`nGit:"
git --version
git status --short --branch

Write-Host "`nPip mirror install command:"
Write-Host "python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt"

Write-Host "`nCUA-Lark doctor:"
python -m cua_lark.cli doctor
