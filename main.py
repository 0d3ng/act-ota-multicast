import os
import sys
import json
import hashlib
import requests
from nacl.signing import SigningKey
import detools

api_url = os.environ.get("API_URL", "").rstrip("/")
api_token = os.environ.get("API_TOKEN", "")
target_version = os.environ.get("TARGET_VERSION", "1.0.0")
private_key_hex = os.environ.get("ED25519_PRIVATE_KEY_HEX", "").strip()

headers = {}
if api_token:
    headers["Authorization"] = f"Bearer {api_token}"

if len(private_key_hex) != 64:
    raise ValueError("Invalid ED25519 private key length. Must be 64 hex characters.")
sk = SigningKey(bytes.fromhex(private_key_hex))

target_fw_path = "build/firmware-ota-rolling-key.bin"
if not os.path.exists(target_fw_path):
    raise FileNotFoundError(f"Target firmware binary not found at {target_fw_path}")

with open(target_fw_path, "rb") as f:
    target_data = f.read()

target_hash = hashlib.sha256(target_data).hexdigest()
target_size = len(target_data)

# -------------------------------------------------------------
# STEP 2: GET /api/v1/firmware-releases/latest?type=full
# -------------------------------------------------------------
print("--> Step 2: Fetching latest full release base version...")
base_version = None
base_fw_url = None

try:
    resp = requests.get(f"{api_url}/firmware-releases/latest?type=full", headers=headers, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        print(f"Latest full release response: {data}")
        if isinstance(data, dict):
            base_version = data.get("target_version") or data.get("version") or data.get("base_version")
            base_fw_url = data.get("file_path")
    else:
        print(f"⚠️ Notice: No previous full release found or endpoint returned HTTP {resp.status_code}")
except Exception as e:
    print(f"⚠️ Notice: Failed to query latest full release: {e}")

print(f"Base Version determined: {base_version}")

# -------------------------------------------------------------
# STEP 3: GET /api/v1/key-generation/current
# -------------------------------------------------------------
print("--> Step 3: Fetching current key generation...")
key_generation = None
try:
    resp = requests.get(f"{api_url}/key-generation/current", headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    print(f"Key generation response: {data}")
    if isinstance(data, dict):
        key_generation = data.get("key_generation")
    elif isinstance(data, int):
        key_generation = data
    if key_generation is None:
        raise ValueError("key_generation field missing from response")
except Exception as e:
    print(f"❌ FATAL: Failed to fetch current key generation: {e}")
    sys.exit(1)

print(f"Key Generation: {key_generation}")

# -------------------------------------------------------------
# STEP 5: Build & sign FULL manifest, then POST /api/v1/firmware-releases
# -------------------------------------------------------------
print("--> Step 5: Building & signing FULL release manifest...")

full_manifest_unsigned = {
    "manifest_version": "2.0",
    "type": "full",
    "base_version": None,
    "target_version": target_version,
    "target_hash": target_hash,
    "target_size": target_size,
    "key_generation": int(key_generation)
}

# Serialize canonically (sorted keys) and sign
canonical_payload = json.dumps(full_manifest_unsigned, sort_keys=True).encode()
full_signature = sk.sign(canonical_payload).signature.hex()

full_manifest = {**full_manifest_unsigned, "signature": full_signature}

with open("manifest_full.json", "w") as f:
    json.dump(full_manifest, f, indent=2)

print(f"FULL Manifest:\n{json.dumps(full_manifest, indent=2)}")

print("Posting FULL release to SEMAR...")

data = {
    "manifest": json.dumps(full_manifest)
}
files = {
    "file": ("firmware.bin", target_data, "application/octet-stream")
}
print(f"DEBUG api_token repr: {repr(api_token)}")
print(f"DEBUG headers: {headers}")
upload_resp = requests.post(f"{api_url}/firmware-releases", headers=headers, data=data, files=files, timeout=60)
print(f"DEBUG request headers actually sent: {upload_resp.request.headers}")
print(f"FULL upload response code: {upload_resp.status_code}")
if upload_resp.status_code not in (200, 201):
    print(f"❌ FULL upload failed: {upload_resp.text}")
    sys.exit(1)
print("✅ FULL release uploaded successfully!")

# -------------------------------------------------------------
# STEP 6: Conditional DELTA release
# -------------------------------------------------------------
if base_version:
    if not base_fw_url:
        print("⚠️ Warning: BASE_VERSION found but download_url is missing from response. Skipping DELTA release.")
    else:
        print(f"--> Step 6: BASE_VERSION found ({base_version}). Generating DELTA release...")
        base_fw_path = "build/base_firmware.bin"
        patch_fw_path = "build/patch.bin"

        # 6a. Fetch base firmware.bin
        print(f"Fetching base firmware binary from {base_fw_url}...")
        base_resp = requests.get(base_fw_url, headers=headers, timeout=60)
        if base_resp.status_code == 200:
            with open(base_fw_path, "wb") as f:
                f.write(base_resp.content)
            print("Base firmware fetched successfully.")

            # 6b. Compute delta patch
            print("Computing diff patch using detools...")
            detools.create_patch_filenames(base_fw_path, target_fw_path, patch_fw_path)

            with open(patch_fw_path, "rb") as f:
                patch_data = f.read()

            delta_hash = hashlib.sha256(patch_data).hexdigest()
            delta_size = len(patch_data)

            # 6c. Build & sign DELTA manifest
            delta_manifest_unsigned = {
                "manifest_version": "2.0",
                "type": "delta",
                "base_version": base_version,
                "target_version": target_version,
                "target_hash": target_hash,
                "delta_hash": delta_hash,
                "delta_algorithm": "detools",
                "delta_size": delta_size,
                "target_size": target_size,
                "key_generation": int(key_generation)
            }

            canonical_delta_payload = json.dumps(delta_manifest_unsigned, sort_keys=True).encode()
            delta_signature = sk.sign(canonical_delta_payload).signature.hex()

            delta_manifest = {**delta_manifest_unsigned, "signature": delta_signature}

            with open("manifest_delta.json", "w") as f:
                json.dump(delta_manifest, f, indent=2)

            print(f"DELTA Manifest:\n{json.dumps(delta_manifest, indent=2)}")

            print("Posting DELTA release to SEMAR...")
            data = {
                "manifest": json.dumps(delta_manifest)
            }
            files = {
                "file": ("firmware.bin", target_data, "application/octet-stream")
            }
            delta_upload_resp = requests.post(f"{api_url}/firmware-releases", headers=headers, data=data, files=files,
                                              timeout=60)
            print(f"DELTA upload response code: {delta_upload_resp.status_code}")
            if delta_upload_resp.status_code not in (200, 201):
                print(f"❌ DELTA upload failed: {delta_upload_resp.text}")
                sys.exit(1)
            print("✅ DELTA release uploaded successfully!")
        else:
            print(f"⚠️ Failed to download base firmware (HTTP {base_resp.status_code}). Skipping DELTA release.")
else:
    print("--> Step 6: BASE_VERSION is null (first release). Skipping DELTA release.")
