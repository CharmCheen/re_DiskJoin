# Reference implementation snapshot

- GitHub: https://github.com/iidyc/DiskJoin
- Clone: `git clone https://github.com/iidyc/DiskJoin.git reference/DiskJoin`
- Pinned commit: `aa86151f97527b1dcf9a032d523c1d67d892454a`
- Last-commit timestamp at inspection: 2025-06-08 UTC
- Known commit message: `fix anonymous github issue caused by file names`
- The repository was created in 2024-11, before the paper's PACMMOD publication.
- **Provenance caveat:** similarity of implementation does not constitute direct confirmation of author attribution or perfect match to the formal VoR. Treat as a strong candidate reference and audit paper/code alignment.
- **License caveat:** no LICENSE file was present at the repository root during inspection. Do not assume permission to redistribute the original sources; this package includes an opt-in downloader instead of copying the GitHub tree.

## On the remote machine

Run `bash scripts/fetch_sources.sh`; it downloads the reference and checks out the exact SHA. The source tree must remain unchanged. Subsequent builds go to `workspace/build` outside source. If `reference/DiskJoin` already exists at a different HEAD, the script aborts without overwriting user content.

## Source paths to read

`expr/main.cpp`, `lib/DiskJoin.h`, `lib/Kmeans.h`, `lib/Gorder.h`, `lib/Cache.h`, `lib/ClusterIO.h`, `lib/ConfigReader.h`, `scripts/run.sh`, `configs/bigann100M_R0.9.config`.
