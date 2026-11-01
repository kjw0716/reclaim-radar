# Security and privacy

Reclaim Radar is a local, single-user Windows application. It binds to loopback and checks request hosts and write origins. There is no remote-user authentication layer. Do not expose port 8765 or the browser debugging port to the internet or a shared network.

The dedicated browser profile contains your Facebook session. `.data/` also contains listings, review history, logs and database backups. Keep it private. `.gitignore` and the release allowlist exclude it, but manually copied folders or attachments may still expose it. Removing a listing does not erase it from existing rotating backups.

Enter passwords and verification codes only on Facebook in the dedicated browser. This project does not solve challenges, message sellers or make purchases. Browser automation and external data sources depend on the platform's current behavior and your account access.

To report a suspected vulnerability, use the repository's private vulnerability reporting feature if enabled. Otherwise contact the repository owner through a private contact method they provide. Do not post credentials, cookie files, database exports or exploit details in a public issue. No private reporting channel or response-time guarantee is supplied by this source template.

Before sharing diagnostic logs or screenshots, review them for seller information, account identifiers, local paths and session data. Reproduce bugs with the isolated demo or a temporary database where possible.
