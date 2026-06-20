$ErrorActionPreference = "Stop"

# Upload BOB-2 project to GitHub under your account.
# Requires: Git + GitHub CLI (gh). If gh is not installed: winget install --id GitHub.cli

$RepoName = "BOB-2"
$GitHubUser = "MoatasimFaroog1111"
$ProjectPath = Join-Path $PSScriptRoot "BOB-2"

if (!(Test-Path $ProjectPath)) {
    Write-Host "❌ Project folder not found: $ProjectPath" -ForegroundColor Red
    exit 1
}

if (!(Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Git is not installed. Install it first: winget install --id Git.Git" -ForegroundColor Red
    exit 1
}

if (!(Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "❌ GitHub CLI is not installed. Run: winget install --id GitHub.cli" -ForegroundColor Red
    exit 1
}

cd $ProjectPath

if (!(Test-Path ".git")) {
    git init
}

git branch -M main

gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    gh auth login
}

# Create repo if it does not exist, otherwise continue.
gh repo view "$GitHubUser/$RepoName" *> $null
if ($LASTEXITCODE -ne 0) {
    gh repo create "$GitHubUser/$RepoName" --private --source=. --remote=origin --push
} else {
    git remote remove origin 2>$null
    git remote add origin "https://github.com/$GitHubUser/$RepoName.git"
    git add .
    git commit -m "Initial upload BOB-2" 2>$null
    git push -u origin main
}

Write-Host "✅ Uploaded successfully: https://github.com/$GitHubUser/$RepoName" -ForegroundColor Green
