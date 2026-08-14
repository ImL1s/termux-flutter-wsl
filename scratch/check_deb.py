import tarfile, os

deb = 'scratch/deb_9b1361a/flutter_3.44.2_aarch64.deb'
os.makedirs('scratch/deb_unpack', exist_ok=True)

with tarfile.open(deb, 'r:*') as t:
    t.extractall('scratch/deb_unpack')

with tarfile.open('scratch/deb_unpack/data.tar.xz', 'r:xz') as dt:
    dt.extractall('scratch/deb_data')

content = open('scratch/deb_data/data/data/com.termux/files/usr/share/flutter/post_install.sh', encoding='utf-8').read()
for line in content.splitlines():
    if 'patch_flutter_cache' in line or '_platform.isAndroid' in line:
        print(line)
