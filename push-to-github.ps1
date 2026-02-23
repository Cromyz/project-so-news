# Script pour pousser sur GitHub - project-so-news
# Executez ce script APRES avoir installe Git
# Si Git n'est pas reconnu : fermez et rouvrez Cursor/VS Code, ou redemarrez le PC

$projectPath = "c:\Users\e.demarslapeyronnie\Documents\projects_dev\project_so_news"
Set-Location $projectPath

# Rafraichir le PATH pour inclure Git
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

# Verifier que Git est disponible
$gitPath = "C:\Program Files\Git\cmd\git.exe"
if (-not (Test-Path $gitPath)) {
    $gitPath = "C:\Program Files (x86)\Git\cmd\git.exe"
}
if (-not (Test-Path $gitPath)) {
    $gitPath = "git"
}

try {
    $null = & $gitPath --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Git failed" }
} catch {
    Write-Host "ERREUR : Git n'est pas installe ou pas dans le PATH." -ForegroundColor Red
    Write-Host "1. Installez Git : https://git-scm.com/download/win"
    Write-Host "2. Ou via winget : winget install Git.Git"
    Write-Host "3. Fermez et rouvrez le terminal apres installation"
    exit 1
}

# Configurer le remote
$remoteUrl = "https://github.com/Cromyz/project-so-news.git"
$remotes = & $gitPath remote 2>$null
if ($remotes -match "origin") {
    & $gitPath remote set-url origin $remoteUrl
} else {
    & $gitPath remote add origin $remoteUrl
}

# Add, commit, push
& $gitPath add .
& $gitPath status
& $gitPath commit -m "UX et reduction API Gemini : suppression synthese, format ids uniquement, recherche par tag sans API"
& $gitPath push -u origin main

Write-Host "`nPush termine !" -ForegroundColor Green
