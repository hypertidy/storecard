#!/bin/bash
# Bucket CORS and a public-read policy scoped to $PREFIX/*.
#
# Dry run by default: shows what exists and what would be applied.
# PutBucketCors and PutBucketPolicy REPLACE the whole bucket config, so:
#   - existing configs are saved to ./backup/ first
#   - an existing policy is merged (our statement appended), never replaced
#   - nothing is applied unless APPLY=1
#
#   bash 01-bucket-setup.sh            # inspect
#   APPLY=1 bash 01-bucket-setup.sh    # apply
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
module load "$PYTHON_MODULE"
AWS="$VENV/bin/aws --profile $AWS_PROFILE --endpoint-url $PAWSEY_ENDPOINT"
PY="$VENV/bin/python"
mkdir -p backup gen
stamp=$(date +%Y%m%dT%H%M%S)

echo "== bucket: $BUCKET   prefix: $PREFIX   apply: ${APPLY:-0}"

# ---- CORS ----
cat > gen/cors.json <<'EOF'
{"CORSRules": [{
  "AllowedOrigins": ["*"],
  "AllowedMethods": ["GET", "HEAD"],
  "AllowedHeaders": ["*"],
  "ExposeHeaders": ["Content-Range", "Content-Length", "ETag", "Accept-Ranges"],
  "MaxAgeSeconds": 3600
}]}
EOF
if $AWS s3api get-bucket-cors --bucket "$BUCKET" > "backup/cors-$stamp.json" 2>/dev/null; then
  echo "-- existing CORS (saved to backup/cors-$stamp.json):"; cat "backup/cors-$stamp.json"
  CORS_EXISTS=1
else
  rm -f "backup/cors-$stamp.json"; echo "-- no CORS configured"; CORS_EXISTS=0
fi
if [ "${APPLY:-0}" = 1 ]; then
  if [ "$CORS_EXISTS" = 1 ] && [ "${FORCE_CORS:-0}" != 1 ]; then
    echo "!! CORS exists; not replacing. Re-run with FORCE_CORS=1 if gen/cors.json is a superset of it."
  else
    $AWS s3api put-bucket-cors --bucket "$BUCKET" --cors-configuration file://gen/cors.json && echo "applied CORS"
  fi
fi

# ---- policy: append a prefix-scoped public GetObject statement ----
if $AWS s3api get-bucket-policy --bucket "$BUCKET" --query Policy --output text > "backup/policy-$stamp.json" 2>/dev/null; then
  echo "-- existing policy saved to backup/policy-$stamp.json"
else
  rm -f "backup/policy-$stamp.json"; echo "-- no bucket policy"
fi
"$PY" -I - "$BUCKET" "$PREFIX" "backup/policy-$stamp.json" gen/policy.json <<'EOF'
import json, os, sys
bucket, prefix, existing, out = sys.argv[1:5]
pol = {"Version": "2012-10-17", "Statement": []}
if os.path.exists(existing):
    pol = json.load(open(existing))
sid = "PortolanFixturesPublicRead"
stmt = {"Sid": sid, "Effect": "Allow", "Principal": {"AWS": ["*"]},
        "Action": ["s3:GetObject"], "Resource": [f"arn:aws:s3:::{bucket}/{prefix}/*"]}
if any(s.get("Sid") == sid for s in pol["Statement"]):
    print("-- policy already has", sid)
else:
    pol["Statement"].append(stmt)
json.dump(pol, open(out, "w"), indent=2)
print("-- policy to apply (gen/policy.json):"); print(json.dumps(pol, indent=2))
EOF
if [ "${APPLY:-0}" = 1 ]; then
  $AWS s3api put-bucket-policy --bucket "$BUCKET" --policy file://gen/policy.json && echo "applied policy"
fi

echo "== done. Check with: bash 04-verify.sh"
