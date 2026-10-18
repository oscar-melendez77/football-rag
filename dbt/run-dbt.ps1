param([Parameter(ValueFromRemainingArguments = $true)] $DbtArgs)

docker run --rm `
    -v "${PSScriptRoot}:/usr/app" `
    -v "$env:APPDATA\gcloud:/root/.config/gcloud:ro" `
    -w /usr/app `
    football-dbt `
    @DbtArgs --profiles-dir /usr/app