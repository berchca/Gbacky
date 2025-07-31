# Gbacky: Simple and Secure Offsite Backups for Linux

**Gbacky** is a easy-to-use offsite backup utility for Debian-based Linux systems (read: Linux Mint and Ubuntu) that syncs your files to an encrypted VeraCrypt vault and then stores off-site on your Google Drive.

For simplicity and speed of a repetitious task, Gbacky runs automatically when the program is started.

<img width="1200" height="514" alt="Gbacky Screenshot" src="https://github.com/user-attachments/assets/ba85a4ee-7407-4cb0-b281-a654860ac435" />


## Installation

Gbacky requires Veracrypt and existing Veracrypt vault somewhere in user's home directory. Since the entire vault will be copied each time the program is run, it is best to keep the size of the vault to a minimum, in regards to the size of the files you are backing up.

Gbacky does not synchronize to Google Drive. Your Veracrypt vault will remain on your local filesystem and a copy will be written to Google Drive. 

For end users:
1.  **Download the `.deb` file** from this page (link to be added). 
2.  **Install the package.** You can usually do this by double-clicking the file or by running the following command in a terminal from the directory where you downloaded the file:
    ```bash
    sudo apt install ./gbacky_*.deb
    ```
    This command will automatically install Gbacky and all of its required dependencies, **except Veracrypt**.
3.  **Install VeraCrypt (if you haven't already).** Gbacky depends on VeraCrypt, but to ensure you get the latest version, it is recommended you install it directly from the official website:
    https://veracrypt.io/
4.  **create a Veracrypt vault.** (as mentioned above, avoid making it excessively large).
5.  **run it** The .deb file should have created an icon in your startup menu. The first time you run Gbacky, it will automatically open the settings window.

## First-Time Setup

The first time you launch Gbacky, the **Settings** window will open automatically, as it needs to be configured. These are the most important options:

1.  **VeraCrypt Vault:** Select an existing VeraCrypt vault file. Gbacky does not create vaults for you.
2.  **Password:** Enter the password for your VeraCrypt vault. You can use the "Test" button to verify your credentials.
3.  **To Backup:** Click "Add Directories..." to select the files and folders you want to back up. These will be synced into the vault.
4.  **GDrive Path:** Gbacky will try to "Detect..." your Google Drive mount point automatically. This is typically a path like `/run/user/1000/gvfs/google-drive:host=...`. 
(untested: If the program finds multiple Google Drives, it should prompt you. If not, you'll have to add the path manually.)
5.  **GDrive Folder:** Specify a folder name within your Google Drive where the vault file will be stored (e.g., `Backups`).
6.  **System Password Option:** By default, Gbacky will ask for your `sudo` password each time it runs(as per Veracrypt). You can uncheck "Always ask for system password" to create a secure, passwordless `sudo` rule specifically for VeraCrypt, allowing for fully automated backups.

Click **Save**, and you're ready to go.

## Usage

-   **Main Screen:** The main window shows the status of the current backup. The backup will run automatically on startup.
-   **Mount / Unmount:** When the program is idle, you can quickly mount and ummount your Veracrypt vault for easy access.
-   **Empty Vault:** This will delete the contents of the mounted vault. Useful for reclaiming space after you've removed directories from your backup list.
-   **Settings:** Click the gear icon at any time to modify your configuration. (or CTRL-S)

## Removal
running the following command in a terminal:
    ```bash
    sudo apt remove gbacky
    ```


## For Developers

If you wish to run the application from the source code:

#### Dependencies

Ensure you have the following packages installed:
```bash
sudo apt install python3-pyside2.qtcore python3-pyside2.qtgui python3-pyside2.qtwidgets python3-keyring python3-secretstorage gir1.2-gtk-3.0 libglib2.0-bin rsync veracrypt
```

#### Running from Source

Clone the repository and run the main script:
```bash
git clone <repository_url>
cd gbacky
python3 Gbacky.py
```

**if you run Gbacky from your own directory, it will use a separate configuration file, et al, stored as Gbacky-dev.** This will allow you to continute to use Gbacky even while you're making those sweet improvements we all know it needs so badly.

#### Building the Package

To share your own version of Gbacky, the `package_deb.py` script will prepare the necessary file structure (update it to include any additional files you created).
1.  Run the packaging script:
    ```bash
    python3 package_deb.py
    ```
2.  Build the `.deb` file using `dpkg-deb`:
    ```bash
    dpkg-deb --build gbacky_VERSION_amd64
    ```
    (Replace `VERSION` with the current version number).

## Development
This program was developed by Brett James with the use of Gemini, with a little touch-up work by Claude Code.

## License

This project is licensed under the AGPL 3.0 License. See the `LICENSE` file for details.
