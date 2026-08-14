import struct, tarfile, os

deb_path = 'scratch/deb_9b1361a/flutter_3.44.2_aarch64.deb'
with open(deb_path, 'rb') as f:
    magic = f.read(8)
    assert magic == b'!<arch>\n'
    while True:
        header = f.read(60)
        if not header or len(header) < 60:
            break
        name = header[:16].decode('ascii').strip()
        size = int(header[48:58].decode('ascii').strip())
        data = f.read(size)
        if size % 2 == 1:
            f.read(1) # padding
        print(f"Ar entry: {name}, size={size}")
        if name.startswith('data.tar'):
            out_name = os.path.join('scratch', name)
            with open(out_name, 'wb') as out_f:
                out_f.write(data)
            print(f"Extracted {out_name}")

            with tarfile.open(out_name, 'r:*') as dt:
                dt.extractall('scratch/deb_data')
            print("Extracted data tarball!")

            post_install_path = 'scratch/deb_data/data/data/com.termux/files/usr/share/flutter/post_install.sh'
            if os.path.exists(post_install_path):
                content = open(post_install_path, encoding='utf-8').read()
                for line in content.splitlines():
                    if 'patch_flutter_cache' in line or '_platform.isAndroid' in line:
                        print(f"POST_INSTALL: {line}")
