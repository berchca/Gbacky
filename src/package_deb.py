#!/usr/bin/env python3

# to build, run:
# dpkg-deb --build gbacky_0.8.0_amd64
# to install:
# sudo apt install ./gbacky_0.8.0_amd64.deb

import os
import shutil
import stat

# --- Configuration ---
# Debian packages prefer lowercase names
APP_NAME = "gbacky"
# Incrementing from Versions.txt. Feel free to change this.
VERSION = "0.8.0"
ARCHITECTURE = "amd64"
# !! IMPORTANT: Replace this with your actual information !!
MAINTAINER = "Your Name <you@example.com>"
DESCRIPTION = """A GUI frontend for an automated VeraCrypt/rsync/Google Drive backup script.
 Gbacky provides a simple graphical interface to manage a robust backup
 process. It handles mounting a local VeraCrypt vault, syncing directories
 into it with rsync, unmounting it, and then copying the vault to a
 Google Drive off-site location.
"""

# --- Derived Paths ---
PACKAGE_DIR = f"{APP_NAME}_{VERSION}_{ARCHITECTURE}"
ICON_FILE = "gbacky.svg"  # The icon for the application (e.g., gbacky.svg or gbacky.png)
SOURCE_FILES = [
    "Gbacky.py",
    "config_utils.py",
    "command_runner.py",
    "credentials_manager.py",
    "file_utils.py",
    "settings.py",
    "settings_io.py",
    "sudo_utils.py",
    "veracrypt_utils.py",
]

def create_directories():
    """Creates the necessary directory structure for the .deb package."""
    print(f"Creating directory structure in ./{PACKAGE_DIR}...")

    # Root directory for the package contents (inside the staging dir)
    install_root = os.path.join(PACKAGE_DIR, "usr")

    # Directory for the executable launcher
    bindir = os.path.join(install_root, "bin")
    os.makedirs(bindir, exist_ok=True)

    # Directory for the application's Python files
    app_share_dir = os.path.join(install_root, "share", APP_NAME)
    os.makedirs(app_share_dir, exist_ok=True)

    # Directory for the .desktop file (for application menu)
    desktop_entry_dir = os.path.join(install_root, "share", "applications")
    os.makedirs(desktop_entry_dir, exist_ok=True)

    # Directory for the application icon
    # Using 'scalable' for SVG. For PNGs, use a sized dir like '48x48'.
    icon_dir = os.path.join(install_root, "share", "icons", "hicolor", "scalable", "apps")
    os.makedirs(icon_dir, exist_ok=True)

    # DEBIAN control directory
    debian_dir = os.path.join(PACKAGE_DIR, "DEBIAN")
    os.makedirs(debian_dir, exist_ok=True)

    return bindir, app_share_dir, debian_dir, desktop_entry_dir, icon_dir

def copy_source_files(app_share_dir):
    """Copies the Python source files into the package structure."""
    print("Copying application source files...")
    for filename in SOURCE_FILES:
        if os.path.exists(filename):
            shutil.copy(filename, app_share_dir)
            print(f"  - Copied {filename}")
        else:
            print(f"  - WARNING: Source file not found: {filename}")

def create_launcher_script(bindir):
    """Creates the executable script that will be placed in /usr/bin."""
    launcher_path = os.path.join(bindir, APP_NAME)
    print(f"Creating launcher script at {launcher_path}...")

    script_content = f"""#!/bin/sh
# Launcher for the Gbacky application
python3 /usr/share/{APP_NAME}/Gbacky.py "$@"
"""

    with open(launcher_path, "w") as f:
        f.write(script_content)

    # Make the launcher executable for all users
    os.chmod(launcher_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    print("  - Made launcher executable.")

def create_desktop_file(desktop_entry_dir):
    """Creates the .desktop file for the application menu."""
    desktop_file_path = os.path.join(desktop_entry_dir, f"{APP_NAME}.desktop")
    print(f"Creating .desktop file at {desktop_file_path}...")

    # Extract the first line of the long description for the comment
    comment = DESCRIPTION.strip().split('\n')[0]

    desktop_content = f"""[Desktop Entry]
Version=1.0
Name=Gbacky
Comment={comment}
Exec={APP_NAME}
Icon={APP_NAME}
Terminal=false
Type=Application
Categories=Utility;System;
"""

    with open(desktop_file_path, "w") as f:
        f.write(desktop_content)
    print("  - .desktop file created.")

def copy_icon_file(icon_dir):
    """Copies the application icon into the package structure."""
    print("Copying application icon...")
    if os.path.exists(ICON_FILE):
        shutil.copy(ICON_FILE, os.path.join(icon_dir, f"{APP_NAME}.svg"))
        print(f"  - Copied {ICON_FILE}")
    else:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"  WARNING: Icon file not found: '{ICON_FILE}'")
        print("  The package will be created without an application icon.")
        print("  Please create this file in your project root directory.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

def create_control_file(debian_dir):
    """Creates the DEBIAN/control file with package metadata."""
    control_file_path = os.path.join(debian_dir, "control")
    print(f"Creating DEBIAN/control file at {control_file_path}...")

    # Dependencies:
    # - python3: The interpreter
    # - python3-pyside2: The Qt GUI toolkit
    # - python3-keyring: For password management
    # - gir1.2-gtk-3.0: Provides 'gio' for Google Drive mounting/detection (part of libglib2.0-bin on some systems)
    # - veracrypt: The core encryption tool
    dependencies = [
        "python3",
        "python3-keyring",
        # PySide2 is split into multiple packages. We need the core components.
        "python3-pyside2.qtcore",
        "python3-pyside2.qtgui",
        "python3-pyside2.qtwidgets",
        "python3-secretstorage", # Recommended backend for python3-keyring on Linux
        "gir1.2-gtk-3.0",
        "libglib2.0-bin", # Provides 'gio'
        "rsync"
    ]

    # Recommends: These are not hard dependencies. The package will install
    # without them, but the functionality will be limited. This is ideal for
    # VeraCrypt, which users often install manually.
    recommends = [
        "veracrypt"
    ]

    control_content = f"""Package: {APP_NAME}
Version: {VERSION}
Architecture: {ARCHITECTURE}
Maintainer: {MAINTAINER}
Depends: {', '.join(dependencies)}
Recommends: {', '.join(recommends)}
Description: {DESCRIPTION.strip()}
"""

    with open(control_file_path, "w") as f:
        f.write(control_content)
    print("  - Control file created.")

def create_postinst_script(debian_dir):
    """Creates the DEBIAN/postinst script to inform the user about VeraCrypt."""
    postinst_path = os.path.join(debian_dir, "postinst")
    print(f"Creating DEBIAN/postinst script at {postinst_path}...")

    script_content = """#!/bin/sh
# postinst script for gbacky
set -e

if [ "$1" = "configure" ]; then
    if ! command -v veracrypt >/dev/null 2>&1; then
        echo "----------------------------------------------------------------------"
        echo " Gbacky requires VeraCrypt to function, but it was not found."
        echo ""
        echo " If you have not installed it yet, please download it from the"
        echo " official website:"
        echo "   https://veracrypt.io/en/Downloads.html"
        echo ""
        echo " After installation, Gbacky should work correctly."
        echo "----------------------------------------------------------------------"
    fi
fi

exit 0
"""
    with open(postinst_path, "w") as f:
        f.write(script_content)

    # Make the postinst script executable
    os.chmod(postinst_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    print("  - Made postinst script executable.")

def create_prerm_script(debian_dir):
    """Creates the DEBIAN/prerm script to clean up the sudoers file on removal."""
    prerm_path = os.path.join(debian_dir, "prerm")
    print(f"Creating DEBIAN/prerm script at {prerm_path}...")

    script_content = """#!/bin/sh
# prerm script for gbacky
# This script is run before the package is removed.
set -e

case "$1" in
    remove|upgrade|deconfigure)
        # Clean up the passwordless sudo file we may have created.
        # The -f flag prevents errors if the file doesn't exist.
        rm -f /etc/sudoers.d/veracrypt-backup-script
    ;;
    failed-upgrade)
    ;;
    *)
        echo "prerm called with unknown argument \`$1'" >&2
        exit 1
    ;;
esac

exit 0
"""
    with open(prerm_path, "w") as f:
        f.write(script_content)

    # Make the prerm script executable
    os.chmod(prerm_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    print("  - Made prerm script executable.")

def main():
    """Main function to orchestrate the packaging preparation."""
    print(f"--- Preparing package: {PACKAGE_DIR} ---")

    if os.path.exists(PACKAGE_DIR):
        print(f"Removing existing directory: ./{PACKAGE_DIR}")
        shutil.rmtree(PACKAGE_DIR)

    bindir, app_share_dir, debian_dir, desktop_entry_dir, icon_dir = create_directories()
    copy_source_files(app_share_dir)
    create_launcher_script(bindir)
    create_desktop_file(desktop_entry_dir)
    copy_icon_file(icon_dir)
    create_control_file(debian_dir)
    create_postinst_script(debian_dir)
    create_prerm_script(debian_dir)

    print("\n--- Preparation Complete ---")
    print("Directory structure created successfully.")
    print(f"\nTo build the .deb package, run the following command:")
    print(f"  dpkg-deb --build {PACKAGE_DIR}")
    print(f"\nTo install the package and its dependencies, use apt:")
    print(f"  sudo apt install ./{PACKAGE_DIR}.deb")
    print("\nNOTE: You may see a harmless 'unsandboxed' notice during installation.")
    print("This is normal when installing a local .deb from your home directory.")
    print("\nRemember to replace the placeholder maintainer info in this script!")

if __name__ == "__main__":
    main()