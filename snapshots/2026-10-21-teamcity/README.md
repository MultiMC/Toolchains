# TeamCity configuration, 2026-10-21

`projects/` is TeamCity's project configuration from deth001
(`/var/lib/teamcity/.BuildServer/config/projects`, TeamCity 2025.07.2), including its own
history copies (`*.xml.1`, `.2`, `.3`). It is the most precise record of how the old builds
ran: build steps, CMake options, container images, triggers, deploy scripts.

Secrets were removed before it went into git:

- every `pluginData/` directory (SSH private keys: BuildBot, SmartMaps BuildBot, the old
  Translator deploy key; the credentials store `secure/credentials.json`)
- scrambled `zxx...` values in old history copies (S3 secret, GitHub tokens, an OAuth client
  secret, a password), replaced by `REDACTED (...)`

What remains: plain parameters, including the S3 access key ID and the paste.ee key (public
in the Launcher anyway), and `credentialsJSON:<id>` references whose values aren't here.

Key files: `MultiMC_Launcher/buildTypes/MultiMC_Launcher_BuildLauncher.xml` (the shared
build template), `MultiMC_Launcher_*/buildTypes/*_Build.xml` (per platform),
`MultiMC_Launcher/buildTypes/MultiMC_Launcher_Deploy.xml` (repoman and S3 deploy),
`MultiMC/project-config.xml` (image names, URLs).
