# portolan-fixtures kit: shared settings. Source this; edit values here only.

# Pawsey Acacia
export PAWSEY_ENDPOINT="${PAWSEY_ENDPOINT:-https://projects.pawsey.org.au}"
export BUCKET="${BUCKET:-aad-derived}"
export PREFIX="${PREFIX:-portolan-fixtures}"
export AWS_PROFILE="${AWS_PROFILE:-pawsey1197}"   # storage project keys (~/.aws/credentials)

export PAWSEY_REMOTE=pawsey1197

# Setonix modules (compute project pawsey1362, storage project pawsey1197)
export PYTHON_MODULE="${PYTHON_MODULE:-python/3.11.6}"
export RCLONE_MODULE="${RCLONE_MODULE:-rclone/1.68.1}"

# Public base URL the fixtures are served at (path-style)
export BASE_URL="${PAWSEY_ENDPOINT}/${BUCKET}/${PREFIX}"

# source.coop, anonymous read through rclone (no keys)
export RCLONE_CONFIG_SRCCOOP_TYPE=s3
export RCLONE_CONFIG_SRCCOOP_PROVIDER=Other
export RCLONE_CONFIG_SRCCOOP_ENDPOINT=https://data.source.coop
export RCLONE_CONFIG_SRCCOOP_ENV_AUTH=false
export RCLONE_CONFIG_SRCCOOP_LIST_VERSION=2        # source.coop needs v2 listing
export RCLONE_CONFIG_SRCCOOP_LIST_URL_ENCODE=false  # and no url-encoded listing
export SRC_ACCOUNT="${SRC_ACCOUNT:-ausantarctic}"

# Working space on Setonix
export WORK="${WORK:-${MYSCRATCH:-/scratch/$PAWSEY_PROJECT/$USER}/portolan-fixtures}"
export VENV="${VENV:-${MYSOFTWARE:-$HOME}/venvs/portolan-fixtures}"

# F01 source month (final OISST files, not _preliminary)
export OISST_MONTH="${OISST_MONTH:-202501}"
export OISST_URL="https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"

# Virtual stores to copy: source prefix under the account -> name under virtual/
VIRTUAL_STORES=(
  "ausantarctic-scratch/oisst/oisst-v2.1-daily"
  "ausantarctic-scratch/seaice/g02202-v6-daily-south"
  "ausantarctic-scratch/bluelink/bluelink-daily-salt"
  "ausantarctic-scratch/ghrsst/ghrsst-mur-cog-analysed_sst"
)
