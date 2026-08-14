import json, urllib.request

with open('sysroot.lock.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Fetch current Packages index to resolve any updated package filenames
req = urllib.request.Request('https://packages-cf.termux.dev/apt/termux-main/dists/stable/main/binary-aarch64/Packages', headers={'User-Agent': 'apt/2.0'})
pkg_index = urllib.request.urlopen(req).read().decode('utf-8')

# Parse package name to filename mapping from Packages index
latest_map = {}
curr_pkg = None
for line in pkg_index.splitlines():
    if line.startswith('Package: '):
        curr_pkg = line.split(': ')[1].strip()
    elif line.startswith('Filename: ') and curr_pkg:
        latest_map[curr_pkg] = line.split(': ')[1].strip()

print(f"Loaded {len(latest_map)} package mappings from Termux apt index.")

updated = 0
for arch_key in ['arm64', 'aarch64']:
    if arch_key not in data:
        continue
    pkgs = data[arch_key]['packages']
    for pkg_name, pkg_info in pkgs.items():
        url = pkg_info.get('url', '')
        # Check if URL returns 200 or 404
        head_req = urllib.request.Request(url, headers={'User-Agent': 'apt/2.0'}, method='HEAD')
        try:
            res = urllib.request.urlopen(head_req)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"⚠ Package {pkg_name} returned 404: {url}")
                if pkg_name in latest_map:
                    new_rel = latest_map[pkg_name]
                    new_url = f"https://packages-cf.termux.dev/apt/termux-main/{new_rel}"
                    print(f"  -> Updating {pkg_name} to: {new_url}")
                    pkg_info['archive_path'] = new_rel
                    pkg_info['url'] = new_url
                    updated += 1
                else:
                    print(f"  ❌ {pkg_name} not found in latest_map!")
            else:
                print(f"HTTP error {e.code} for {pkg_name}: {e}")

if updated > 0:
    with open('sysroot.lock.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    print(f"✓ Successfully updated {updated} stale package URLs in sysroot.lock.json")
else:
    print("✓ All package URLs in sysroot.lock.json are valid and returning 200 OK.")
