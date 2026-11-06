# Setonix / Pawsey Acacia runbook

How the published fixture set is built and hosted: Slurm jobs on Setonix
write to a Pawsey Acacia bucket. Run everything from this `setonix/`
directory. Settings live in `config.sh`; edit only that file.

| File | Where it runs | What it does |
| ---- | ------------- | ------------ |
| `config.sh` | sourced | bucket, prefix, rclone remote, source.coop anonymous remote, store list |
| `00-env.sh` | login node, once | venv on python/3.11.6 with xarray, zarr 3, netCDF4, pyproj, awscli; bucket visibility check |
| `01-bucket-setup.sh` | login node | CORS + prefix-scoped public read; dry run unless `APPLY=1` |
| `02-copy-virtual.sbatch` | copy partition | copies 4 virtual indexes from source.coop (about 3.7 GiB) |
| `03-build-f01.sbatch` | copy partition | downloads one OISST month, builds the F01 twins + catalog, uploads (uses `../build/`) |
| `04-verify.sh` | anywhere | cross-origin Range checks on Pawsey, source.coop and upstream hosts |
| `../bucket/README.md`, `../bucket/AGENTS.md` | uploaded | catalog root README and AGENTS.md |

## Steps

1. Clone the repo on Setonix and `cd portolan-kit/setonix`. `mkdir -p logs`.

2. Check `config.sh`: `BUCKET`, `PREFIX`, and `AWS_PROFILE` (pawsey1197, the
   storage project). rclone reads the same keys through that profile; no
   rclone.conf is needed. Jobs are charged to the compute project (pawsey1362).

3. `bash 00-env.sh` (builds the venv on python/3.11.6, then checks that the
   keys can see the bucket)

4. `bash 01-bucket-setup.sh` and read the output. It saves any existing CORS
   and policy into `backup/`. If the bucket already has CORS, it will not
   replace it unless `FORCE_CORS=1` (only do that if `gen/cors.json` covers
   what was there). An existing policy is merged, not replaced: check
   `gen/policy.json`. Then:
   `APPLY=1 bash 01-bucket-setup.sh`

5. Submit the two jobs (independent of each other):
   ```
   sbatch --account=pawsey1362 02-copy-virtual.sbatch
   sbatch --account=pawsey1362 03-build-f01.sbatch
   ```
   `DRY=1 sbatch ...` does an rclone dry run of the copy job.

6. `bash 04-verify.sh`. Each line is `status acao=... expose=... url`.
   - `206 acao=*` on the Pawsey and source.coop lines is the pass.
   - The upstream lines (NCEI, noaadata.apps.nsidc.org) tell you whether a
     browser can follow the virtual references at all. No `acao` there means
     the virtual stores cannot draw in a browser from anywhere, which is a
     finding for issue 132, not a bucket problem.
   - The last line should be 403 (listing denied).

7. Point the browser at `https://projects.pawsey.org.au/<bucket>/<prefix>/catalog/catalog.json`
   (portolan-browser PR 92 branch, or its harness via `CATALOG_URL`).

## Known so far

- source.coop needs list version 2 with no URL encoding for rclone; set in
  `config.sh`.
- The OISST virtual index references `https://www.ncei.noaa.gov/...`, which
  answers cross-origin range reads (`acao=*`, no exposed headers). The G02202
  index references `https://noaadata.apps.nsidc.org/...`, which sends no CORS
  header, so no browser can follow those references (see `docs/results-2026-11-06.md`).
- `aad-derived` already had the needed CORS rule and a bucket-wide public read
  and list policy, so `01-bucket-setup.sh` applied nothing; listing returns 200.
- The G02202 virtual store has no `crs` grid mapping variable (only
  `cdr_seaice_conc`, `time`, `x`, `y`), so a CRS check refuses it as published.
  Fix in raad.virtualize, not here.
- F01 stores use 360 x 360 inner chunks for every twin; the native OISST
  layout (one 720 x 1440 chunk per day) is what the copied virtual index has.
- `00-env.sh` rebuilds the venv if its Python does not match the module's
  (a venv left over from the system Python 3.6 otherwise offers xarray 0.16).
