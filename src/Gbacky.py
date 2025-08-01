#!/usr/bin/env python3
#
# === GUI Frontend for the Automated Backup Script ===
#
# This application provides a simple graphical interface for the backup script
# using PySide2 (Qt5).
#
# It runs the backup process in a separate thread to keep the UI responsive
# and displays all output in a text area.
#
# NOTE: This script still requires the same passwordless sudo setup for
# 'veracrypt' as the command-line version. Please see the header in
# 'GDBack.py' for instructions if you haven't set that up yet.
#

import os
import sys
import subprocess
import hashlib
import shutil
import json
import time
import concurrent.futures
from datetime import datetime

from PySide2.QtWidgets import (QApplication, QWidget, QVBoxLayout,
                               QPlainTextEdit, QPushButton, QHBoxLayout, QStackedLayout,
                               QLabel, QToolButton, QStyle, QFormLayout, QLineEdit, QFileDialog, QSizePolicy, QGridLayout, QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView, QCheckBox, QInputDialog,
                               QSpinBox, QProgressBar, QAction)
from PySide2.QtCore import QObject, Signal, Slot, QThread, Qt, QTimer, QSize
from PySide2.QtGui import QFont, QIntValidator, QColor, QKeySequence

from config_utils import load_config, save_config
from settings_io import export_settings_to_file, import_settings_from_file
from sudo_utils import is_password_required, setup_passwordless_sudo, remove_passwordless_sudo, verify_sudo_password
from settings import SettingsWindow
from file_utils import copy_file_with_watchdog, calculate_sha256_with_watchdog, calculate_sha256_local, CancellationError
from command_runner import run_command, run_with_timeout
from veracrypt_utils import get_mount_point
from credentials_manager import get_veracrypt_password, set_veracrypt_password


RSYNC_OPTIONS = "-azhi"  # Use 'i' for itemize-changes instead of 'v' for verbose

# Error codes for better error handling
class StatusCodes:
    # UI States
    NEEDS_CONFIG = "NEEDS_CONFIG"
    CONFIG_ERROR = "CONFIG_ERROR"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    STOPPED = "STOPPED"
    # Error States
    GDRIVE_NOT_MOUNTED = "GDRIVE_NOT_MOUNTED"
    GDRIVE_WRITE_FAILED = "GDRIVE_WRITE_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DISK_FULL = "DISK_FULL"
    NETWORK_ERROR = "NETWORK_ERROR"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    GENERAL_ERROR = "GENERAL_ERROR"

class BackupWorker(QObject):
    """
    Runs the backup process in a separate thread.
    Emits signals to update the GUI with progress and results.
    """
    # Timeout arrays for different network quality levels
    # [io_timeout, cmd_timeout, probe_timeout]
    TIMEOUTS_GOOD = [45, 30, 10]       # Good network connection
    TIMEOUTS_POOR = [135, 90, 30]      # Poor network connection (3x good)
    # Use very long, but finite, timeouts for terrible connections to prevent
    # the application from hanging indefinitely on an unresponsive network mount.
    # Using 'None' for a timeout means "wait forever".
    TIMEOUTS_TERRIBLE = [3600, 1800, 600] # Terrible connection (1hr, 30min, 10min timeouts)
    
    # Signals to communicate with the main GUI thread
    log_message = Signal(str)   # Emits a line of log text
    status_update = Signal(str) # Emits a high-level status update
    step_changed = Signal(str)  # Emits the name of the current step for cancellation logic
    progress_update = Signal(int) # Emits progress percentage (0-100)
    finished = Signal()               # Emits when the worker is done, for thread cleanup
    main_status_changed = Signal(str, str)  # Emits status_code, details

    def __init__(self, config, profile, sudo_password=None):
        super().__init__()
        self.config = config
        self.profile = profile
        self.sudo_password = sudo_password
        
        # Get network quality setting and set timeouts accordingly
        network_quality = self.config.get("NETWORK_QUALITY", 0)  # 0=good, 1=poor, 2=terrible
        if network_quality == 0:
            timeouts = self.TIMEOUTS_GOOD
        elif network_quality == 1:
            timeouts = self.TIMEOUTS_POOR
        else:  # network_quality == 2
            timeouts = self.TIMEOUTS_TERRIBLE
            
        self.io_timeout = timeouts[0]
        self.cmd_timeout = timeouts[1]
        self.probe_timeout = timeouts[2]

        self.was_successful = True
        self.current_step = ""
        self._cancellation_requested = False
        self.was_cancelled = False

    def request_cancellation(self):
        """Sets a flag to gracefully stop the backup process."""
        self._cancellation_requested = True

    def _emit_main_status_change(self, status_code, details=""):
        """Helper to emit a main status change signal and track success."""
        # Any status that isn't explicitly a success/stopped state is a failure.
        if status_code not in [StatusCodes.COMPLETE, StatusCodes.STOPPED]:
            self.was_successful = False
        self.main_status_changed.emit(status_code, details)

    def _attempt_google_drive_mount(self, gdrive_path):
        """Attempts to mount Google Drive using gio mount."""
        try:
            # Check for cancellation before starting a potentially long operation.
            if self._cancellation_requested:
                self.log_message.emit("Cancellation requested, skipping Google Drive mount attempt.")
                return False

            # Extract email from the GVFS path if possible
            # Path format: /run/user/{uid}/gvfs/google-drive:host=gmail.com,user=brett.the.james/...
            user_email = None
            host = None
            
            if "/gvfs/google-drive:" in gdrive_path:
                parts = gdrive_path.split("google-drive:")
                if len(parts) > 1:
                    mount_info = parts[1].split("/")[0]  # Get the part before the first /
                    for param in mount_info.split(","):
                        if param.startswith("user="):
                            user_email = param.split("=", 1)[1]
                        elif param.startswith("host="):
                            host = param.split("=", 1)[1]
            
            # Reconstruct full email address if we have both parts
            if user_email and host:
                if "@" not in user_email:  # user_email is just the username part
                    full_email = f"{user_email}@{host}"
                else:  # user_email is already complete
                    full_email = user_email
            else:
                self.log_message.emit(f"Could not extract email info from Google Drive path: {gdrive_path}")
                self.log_message.emit(f"Extracted user: {user_email}, host: {host}")
                return False
                
            self.log_message.emit(f"Attempting to mount Google Drive for {full_email}...")
            self.status_update.emit("Attempting to mount Google Drive...")
            
            # Use gio mount to mount the Google Drive
            mount_uri = f"google-drive://{full_email}/"
            run_kwargs = {
                'capture_output': True,
                'text': True
            }
            if self.cmd_timeout is not None:
                run_kwargs['timeout'] = self.cmd_timeout
            result = subprocess.run(['gio', 'mount', mount_uri], **run_kwargs)
            
            if result.returncode == 0:
                self.log_message.emit("Google Drive mount successful")
                return True # The calling function will now poll for readiness.
            else:
                self.log_message.emit(f"Google Drive mount failed: {result.stderr.strip()}")
                return False
                
        except subprocess.TimeoutExpired:
            self.log_message.emit("Google Drive mount attempt timed out")
            return False
        except Exception as e:
            self.log_message.emit(f"Error attempting to mount Google Drive: {e}")
            return False

    def _check_prerequisites(self):
        """Verify that required commands exist."""
        if not shutil.which("veracrypt"):
            self._emit_main_status_change(StatusCodes.GENERAL_ERROR, "'veracrypt' command not found.")
            return False
        if not shutil.which("rsync"):
            self._emit_main_status_change(StatusCodes.GENERAL_ERROR, "'rsync' command not found.")
            return False
        return True

    @Slot()
    def run(self):
        """The main logic for the backup process."""
        mount_point = None
        did_i_mount_it = False
        try:
            self.current_step = "STARTING"; self.step_changed.emit(self.current_step)
            if not self._check_prerequisites():
                return

            home_dir = os.path.expanduser('~')
            veracrypt_vault = os.path.join(home_dir, self.profile["VERACRYPT_VAULT"])
            backup_dirs = [os.path.join(home_dir, d) for d in self.profile["BACKUP_DIRS"]]

            # --- Retrieve password from keyring ---
            self.status_update.emit("Retrieving credentials...")
            veracrypt_password = get_veracrypt_password(self.profile["VERACRYPT_VAULT"])
            if not veracrypt_password:
                self._emit_main_status_change(StatusCodes.GENERAL_ERROR, "Could not retrieve VeraCrypt password from system keyring. Please save it in Settings.")
                return
            # ---

            base_command = ["veracrypt", "--text", "--non-interactive"]

            # --- Step 1: Check for existing mount ---
            self.current_step = "CHECKING_MOUNT"; self.step_changed.emit(self.current_step)
            self.status_update.emit("Step 1: Checking VeraCrypt vault status...")
            if self._cancellation_requested: raise CancellationError("Backup cancelled by user.")

            mount_point = get_mount_point(veracrypt_vault, self.sudo_password, self.log_message.emit)

            if mount_point:
                self.status_update.emit(f"Vault already mounted at {mount_point}. Skipping mount step.")
            else:
                # --- Step 1b: Mount the vault ---
                self.current_step = "MOUNTING"; self.step_changed.emit(self.current_step)
                self.status_update.emit("Step 1: Mounting VeraCrypt Vault...")
                if not os.path.exists(veracrypt_vault):
                    self._emit_main_status_change(StatusCodes.GENERAL_ERROR, f"VeraCrypt vault not found at '{veracrypt_vault}'.")
                    return
                
                mount_args = ["--mount", veracrypt_vault, "--password", veracrypt_password]
                mount_command = base_command + mount_args

                if self._cancellation_requested: raise CancellationError("Backup cancelled by user.")
                process = run_command(mount_command, sudo_password=self.sudo_password, log_callback=self.log_message.emit)
                if process is None:
                    self._emit_main_status_change(StatusCodes.GENERAL_ERROR, "Failed to mount VeraCrypt vault.")
                    return
                
                did_i_mount_it = True
                mount_point = get_mount_point(veracrypt_vault, self.sudo_password, self.log_message.emit)
                if not mount_point:
                    # This is a safety dismount, in case it mounted but we can't find it.
                    dismount_command = base_command + ["--dismount", veracrypt_vault]
                    # We don't care about the result of this safety dismount, just that we tried.
                    run_command(dismount_command, sudo_password=self.sudo_password, log_callback=self.log_message.emit)
                    self._emit_main_status_change(StatusCodes.GENERAL_ERROR, "Could not determine mount point after mounting.")
                    return

            # --- Step 2: Rsync ---
            self.current_step = "RSYNCING"; self.step_changed.emit(self.current_step)
            self.status_update.emit(f"Vault is ready at: {mount_point}")
            self.status_update.emit("Step 2: Backing up directories with rsync...")
            for src_dir in backup_dirs:
                if not os.path.exists(src_dir):
                    self.log_message.emit(f"Warning: Source directory not found, skipping: {src_dir}")
                    continue
                if self._cancellation_requested: raise CancellationError("Backup cancelled by user.")
                self.log_message.emit(f"\nBacking up '{os.path.basename(src_dir)}'...")
                rsync_command = ["rsync", RSYNC_OPTIONS, src_dir, mount_point]
                rsync_filter = lambda line: line if line.startswith('>') else None
                # rsync doesn't need sudo
                if run_command(rsync_command, log_callback=self.log_message.emit, output_filter=rsync_filter) is None:
                    self.log_message.emit(f"ERROR: Failed to back up {src_dir}. Continuing...")
            self.status_update.emit("Local backup to vault complete.")

            # --- Step 3: Unmount (if we mounted it) ---
            if did_i_mount_it:
                self.current_step = "UNMOUNTING"; self.step_changed.emit(self.current_step)
                self.status_update.emit("Step 3: Unmounting VeraCrypt Vault...")
                dismount_command = base_command + ["--dismount", mount_point]
                run_command(dismount_command, sudo_password=self.sudo_password, log_callback=self.log_message.emit)
                mount_point = None # Mark as unmounted

            # --- Step 4: Off-site Backup ---
            self.current_step = "PREPARING_GDRIVE"; self.step_changed.emit(self.current_step)
            self.status_update.emit("Step 4: Starting off-site backup to Google Drive...")
            gdrive_path = self.config.get("GOOGLE_DRIVE_PATH")
            if not gdrive_path:
                self.log_message.emit("Google Drive path not configured. Skipping.")
                return

            dest_dir = os.path.join(gdrive_path, self.config["GOOGLE_DRIVE_BACKUP_DIR"])
            self.status_update.emit("Verifying Google Drive is mounted...")
            if self._cancellation_requested: raise CancellationError("Backup cancelled by user.")
            # To prevent a core dump when accessing a dead FUSE mount (like gvfs),
            # we probe the path and create the directory using external commands with
            # a timeout. This is much safer than using Python's 'os' module directly,
            # which can crash the entire application if the mount is hung.

            # Step 4a: Probe the base directory. 'test -d' is a lightweight check.
            gdrive_path_accessible = False
            try:
                self.log_message.emit(f"Probing Google Drive base path: {gdrive_path}")
                # Use the watchdog to run the command safely.
                run_with_timeout(
                    subprocess.run,
                    args=(['test', '-d', gdrive_path],),
                    kwargs={'check': True},
                    timeout=self.probe_timeout
                )
                gdrive_path_accessible = True
            except (subprocess.CalledProcessError, TimeoutError):
                # Path is not accessible or timed out. Try to auto-mount if enabled.
                if self.config.get("AUTO_MOUNT_GDRIVE", True):
                    if self._attempt_google_drive_mount(gdrive_path):
                        self.log_message.emit("Auto-mount successful, waiting for filesystem to become responsive...")
                        # After a successful mount, the filesystem might not be ready immediately.
                        # We'll poll it a few times before giving up.
                        for i in range(5): # Retry up to 5 times (total of ~4 seconds wait)
                            try:
                                run_with_timeout(
                                    subprocess.run,
                                    args=(['test', '-d', gdrive_path],),
                                    kwargs={'check': True},
                                    timeout=self.probe_timeout
                                )
                                gdrive_path_accessible = True
                                self.log_message.emit("Google Drive path now accessible after auto-mount.")
                                break # Success, exit the retry loop
                            except (subprocess.CalledProcessError, TimeoutError):
                                if i < 4: # Don't sleep on the last attempt
                                    self.log_message.emit(f"Path not ready yet, retrying in 1 second... ({i+1}/4)")
                                    time.sleep(1)
                                else:
                                    # All retries failed
                                    pass

            except Exception as e:
                self._emit_main_status_change(StatusCodes.GENERAL_ERROR, f"Unexpected error checking Google Drive path: {e}")
                return

            if not gdrive_path_accessible:
                self._emit_main_status_change(StatusCodes.GDRIVE_NOT_MOUNTED, f"Google Drive path is not accessible or not responding: {gdrive_path}")
                return

            # Step 4b: Create the destination directory. 'mkdir -p' is like os.makedirs(exist_ok=True).
            try:
                self.log_message.emit(f"Ensuring backup directory exists: {dest_dir}")
                run_with_timeout(
                    subprocess.run,
                    args=(['mkdir', '-p', dest_dir],),
                    kwargs={'check': True},
                    timeout=self.cmd_timeout
                )
            except (subprocess.CalledProcessError, TimeoutError) as e:
                self._emit_main_status_change(StatusCodes.GDRIVE_WRITE_FAILED, f"Could not create Google Drive directory: {dest_dir}\nError: {e}")
                return
            except Exception as e:
                self._emit_main_status_change(StatusCodes.GENERAL_ERROR, f"Unexpected error creating Google Drive directory: {e}")
                return
            
            self.current_step = "COPYING_TO_GDRIVE"; self.step_changed.emit(self.current_step)
            dest_file_path = os.path.join(dest_dir, os.path.basename(veracrypt_vault))
            # Perform the copy and hashing using the new utility functions
            copy_file_with_watchdog(
                veracrypt_vault,
                dest_file_path,
                status_update_callback=self.status_update.emit,
                cancellation_check_callback=lambda: self._cancellation_requested,
                log_callback=self.log_message.emit,
                io_timeout=self.io_timeout,
                progress_callback=self.progress_update.emit
            )

            source_hash = calculate_sha256_local(
                veracrypt_vault,
                status_update_callback=self.status_update.emit,
                cancellation_check_callback=lambda: self._cancellation_requested
            )
            dest_hash = calculate_sha256_with_watchdog(
                dest_file_path,
                status_update_callback=self.status_update.emit,
                cancellation_check_callback=lambda: self._cancellation_requested,
                log_callback=self.log_message.emit,
                io_timeout=self.io_timeout,
                progress_callback=self.progress_update.emit
            ) 
            if not (source_hash and dest_hash and source_hash == dest_hash):
                self._emit_main_status_change(StatusCodes.VERIFICATION_FAILED, "The SHA256 hashes of the source and destination files do not match.")
                try:
                    os.remove(dest_file_path)
                    self.log_message.emit("The corrupt destination file has been deleted.")
                except OSError as e:
                    self.log_message.emit(f"ERROR: Could not delete corrupt file: {e}")

        except CancellationError as e:
            self.log_message.emit(f"--- {e} ---") # Log the cancellation message
            self.was_cancelled = True

        except (IOError, OSError, TimeoutError) as e:
            # The file_utils and other functions are designed to raise exceptions
            # with user-friendly messages. We just pass the original message along.
            message = str(e)
            message_lower = message.lower()
            
            # Check for mount-related errors
            mount_error_keywords = ["not responding", "timed out", "hang"]
            is_mount_error = any(keyword in message_lower for keyword in mount_error_keywords)
            
            if is_mount_error and ("google drive" in message_lower or "gdrive" in message_lower):
                self._emit_main_status_change(StatusCodes.GDRIVE_NOT_MOUNTED, message)
            elif "google drive" in message_lower or "gdrive" in message_lower:
                self._emit_main_status_change(StatusCodes.GDRIVE_WRITE_FAILED, message)
            elif "permission denied" in message_lower:
                self._emit_main_status_change(StatusCodes.PERMISSION_DENIED, message)
            elif "no space" in message_lower or "disk full" in message_lower:
                self._emit_main_status_change(StatusCodes.DISK_FULL, message)
            elif any(keyword in message_lower for keyword in ["network", "connection", "timeout", "unreachable"]):
                self._emit_main_status_change(StatusCodes.NETWORK_ERROR, message)
            else:
                self._emit_main_status_change(StatusCodes.GENERAL_ERROR, message)
        finally:
            # Emit final status before finishing
            if self.was_cancelled:
                self._emit_main_status_change(StatusCodes.STOPPED)
            elif self.was_successful:
                self._emit_main_status_change(StatusCodes.COMPLETE)

            if mount_point:
                self.log_message.emit("Ensuring vault is unmounted after an issue...")
                dismount_command = ["veracrypt", "--text", "--non-interactive", "--dismount", mount_point]
                run_command(dismount_command, sudo_password=self.sudo_password, log_callback=self.log_message.emit)
            self.finished.emit()


class VaultActionWorker(QObject):
    """
    A dedicated worker for simple, one-off vault actions like mounting,
    unmounting, and emptying, performed in a background thread.
    """
    log_message = Signal(str)     # Emits a line of log text
    finished = Signal()           # Emits when the action is complete
    status_updated = Signal(bool) # Emits (is_mounted)

    def __init__(self, config, profile, sudo_password=None):
        super().__init__()
        self.config = config
        self.profile = profile
        self.sudo_password = sudo_password

    @Slot(str)
    def run(self, mode):
        """The main entry point for the worker's actions."""
        home_dir = os.path.expanduser('~')
        vault_path_relative = self.profile.get("VERACRYPT_VAULT", "")
        vault_path = os.path.join(home_dir, vault_path_relative) if vault_path_relative else ""

        # Retrieve password from keyring
        veracrypt_password = get_veracrypt_password(vault_path_relative)
        if not vault_path or not veracrypt_password:
            self.log_message.emit("ERROR: VeraCrypt vault or password is not configured in Settings.")
            self.finished.emit()
            return

        base_command = ["veracrypt", "--text", "--non-interactive"]
        mount_point = get_mount_point(vault_path, self.sudo_password)

        if mode == "CHECK_STATUS":
            self.status_updated.emit(mount_point is not None)

        elif mode == "TOGGLE_MOUNT":
            if mount_point: # Unmount
                self.log_message.emit("--- Unmounting vault... ---")
                cmd = base_command + ["--dismount", mount_point]
                run_command(cmd, sudo_password=self.sudo_password, log_callback=self.log_message.emit)
            else: # Mount
                self.log_message.emit("--- Mounting vault... ---")
                args = ["--mount", vault_path, "--password", veracrypt_password]
                cmd = base_command + args
                run_command(cmd, sudo_password=self.sudo_password, log_callback=self.log_message.emit)
            
            new_mount_point = get_mount_point(vault_path, self.sudo_password)
            if mount_point and not new_mount_point:
                self.log_message.emit("Unmount successful.")
            elif not mount_point and new_mount_point:
                self.log_message.emit(f"Mount successful. New mount point: {new_mount_point}")
            else:
                self.log_message.emit("Mount/Unmount state did not change as expected. Please check the details panel.")

            self.status_updated.emit(new_mount_point is not None)

        elif mode == "EMPTY_VAULT":
            if not mount_point:
                self.log_message.emit("ERROR: Vault must be mounted to be emptied.")
                self.finished.emit()
                return
            self.log_message.emit("--- Emptying vault... ---")
            try:
                for filename in os.listdir(mount_point):
                    file_path = os.path.join(mount_point, filename)
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                self.log_message.emit("Vault emptied successfully.")
            except Exception as e:
                self.log_message.emit(f"ERROR: Failed to empty vault: {e}")
        
        self.finished.emit()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Google Drive Backup")

        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Top Control Panel (Main View) ---
        control_panel = QWidget()
        control_panel.setFixedHeight(450) # Keep the height for consistent layout
        # control_panel.setStyleSheet("background-color: beige;") # Removed to use native theme
        control_layout = QVBoxLayout(control_panel)
        control_layout.setSpacing(10)
        control_layout.setContentsMargins(10, 10, 10, 10)

        # --- Action Buttons (Mount/Empty) ---
        self.mount_button = QPushButton("Mount")
        self.empty_vault_button = QPushButton("Empty Vault")

        action_button_font = QFont()
        action_button_font.setPixelSize(20) # Slightly smaller than info line for balance
        self.mount_button.setFont(action_button_font)
        self.empty_vault_button.setFont(action_button_font)

        action_button_layout = QHBoxLayout()
        action_button_layout.setContentsMargins(15, 5, 15, 5)
        action_button_layout.addWidget(self.mount_button)
        action_button_layout.addWidget(self.empty_vault_button)
        action_button_layout.addStretch()

        self.action_button_widget = QWidget()
        self.action_button_widget.setLayout(action_button_layout)
        self.action_button_widget.setVisible(False) # Hidden by default

        # 1. Branding Box (Placeholder for image)
        branding_container = QWidget()
        branding_container.setFixedHeight(100)
        # Use a QGridLayout to robustly handle centering and right-alignment.
        header_layout = QGridLayout(branding_container)
        header_layout.setContentsMargins(10, 0, 10, 0)

        # The centered title
        branding_label = QLabel("Gbacky")
        branding_label.setAlignment(Qt.AlignCenter)
        branding_font = QFont()
        branding_font.setPixelSize(80) # Set font to be 80px tall
        branding_font.setBold(True)
        branding_label.setFont(branding_font)

        # The settings button
        self.settings_button = QToolButton()
        self.settings_button.setToolTip("Open Settings (Ctrl+S)")
        icon = self.style().standardIcon(QStyle.SP_FileDialogDetailedView)
        self.settings_button.setIcon(icon)
        self.settings_button.setIconSize(QSize(48, 48))
        self.settings_button.setAutoRaise(True) # Flat until hovered

        # The label spans all columns and is centered within that space.
        header_layout.addWidget(branding_label, 0, 0, 1, 3)
        # The button is placed in the rightmost column (column 2), aligned to the right.
        header_layout.addWidget(self.settings_button, 0, 2, Qt.AlignRight)

        # 3. Information Line (Vault and Destination)
        info_widget = QWidget()
        info_widget.setFixedHeight(60)
        info_layout = QHBoxLayout(info_widget)
        info_layout.setContentsMargins(15, 0, 15, 0)
        self.vault_info_label = QLabel("")
        self.dest_info_label = QLabel("")
        info_font = QFont()
        info_font.setPixelSize(24)
        self.vault_info_label.setFont(info_font)
        self.dest_info_label.setFont(info_font)
        info_layout.addWidget(self.vault_info_label, alignment=Qt.AlignLeft)
        info_layout.addWidget(self.dest_info_label, alignment=Qt.AlignRight)

        # 2. "Running" Status Box (Moved after info line for correct ordering)
        self.running_status_label = QLabel("IDLE")
        self.running_status_label.setFixedHeight(40)
        self.running_status_label.setAlignment(Qt.AlignCenter)
        running_font = QFont()
        running_font.setPointSize(18)
        running_font.setBold(True)
        self.running_status_label.setFont(running_font)
        self.running_status_label.setStyleSheet("background-color: #4CAF50; color: white; border-radius: 5px;") # Green for idle

        # 4. Step-by-step Status Label
        self.status_label = QLabel("Click 'Backup' to start.")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = self.status_label.font()
        status_font.setPointSize(14)
        self.status_label.setFont(status_font)
        
        # 4a. Progress Bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setTextVisible(True)

        # 5. Buttons - "Backup" button is now a "Try Again" button, hidden by default.
        self.backup_button = QPushButton("Try Backup Again")
        self.backup_button.setVisible(False)
        self.close_button = QPushButton("Close")
        self.toggle_details_button = QToolButton()
        self.toggle_details_button.setText("Show Details")
        self.toggle_details_button.setArrowType(Qt.DownArrow)
        self.toggle_details_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_details_button.setToolTip("Show or hide the detailed log output")

        footer_button_layout = QHBoxLayout()
        footer_button_layout.addWidget(self.toggle_details_button)
        footer_button_layout.addStretch()
        footer_button_layout.addWidget(self.backup_button)
        footer_button_layout.addWidget(self.close_button)

        # Assemble the control panel layout
        control_layout.addWidget(branding_container)
        control_layout.addWidget(self.running_status_label)
        control_layout.addWidget(info_widget)
        control_layout.addWidget(self.action_button_widget)
        control_layout.addStretch()
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.progress_bar)
        control_layout.addLayout(footer_button_layout)


        # --- Bottom Details Panel (collapsible) ---
        self.details_panel = QWidget()
        details_layout = QVBoxLayout(self.details_panel)
        details_layout.setContentsMargins(5, 5, 5, 5)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        log_font = QFont("Monospace")
        log_font.setStyleHint(QFont.TypeWriter)
        log_font.setPointSize(9) # A smaller font size fits more columns
        self.log_box.setFont(log_font)
        self.log_box.setLineWrapMode(QPlainTextEdit.WidgetWidth)

        details_layout.addWidget(self.log_box)
        self.details_panel.setVisible(False) # Start collapsed
        self.details_panel.setFixedHeight(400)

        # --- Assemble Main Window ---
        main_layout.addWidget(control_panel)
        main_layout.addWidget(self.details_panel)

        # --- Threading ---
        self.thread = None
        self.worker = None
        self.settings_window = None
        self.config = None
        self.current_profile = None
        self.last_sudo_password = None
        self.current_backup_step = ""
        self.last_status_code = ""
        self.is_first_run = False # Flag for initial setup
        self.is_backup_running = False # Track if the backup thread is active
        self.countdown_seconds = 0
        self._close_on_finish = False # Flag to close after backup stops
        self.close_timer = QTimer(self)

        # --- Connections ---
        self.settings_button.clicked.connect(self.open_settings)

        # Add Ctrl+S shortcut for opening settings
        open_settings_action = QAction("Open Settings", self)
        open_settings_action.setShortcut(QKeySequence("Ctrl+S"))
        open_settings_action.triggered.connect(self.open_settings)
        self.addAction(open_settings_action)

        # Add Ctrl+Q shortcut for quitting
        quit_action = QAction("Quit Application", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.quit_application)
        self.addAction(quit_action)

        self.toggle_details_button.clicked.connect(self.toggle_details)
        self.backup_button.clicked.connect(self.run_backup_process)
        self.close_button.clicked.connect(self.close)
        self.mount_button.clicked.connect(self.on_mount_button_clicked)
        self.empty_vault_button.clicked.connect(self.on_empty_vault_button_clicked)
        self.close_timer.timeout.connect(self.update_countdown)

        # Set the initial fixed size for the window (control panel only)
        self.setFixedSize(1200, 450)

        # Load config on startup and decide the initial state
        self.config, error_msg = load_config()
        run_backup_on_startup = True

        if not self.config:
            run_backup_on_startup = False
            if "not found" in error_msg:
                # First run: open settings automatically.
                self.update_main_status(StatusCodes.NEEDS_CONFIG)
                self.config = {} # Create an empty config to pass to the settings window
                self.highlight_settings_button()
                self.is_first_run = True # Set flag to open settings after window is shown
            else:
                # Config is present but invalid.
                self.update_main_status(StatusCodes.CONFIG_ERROR, error_msg)
        else:
            # Config loaded successfully.
            self.current_profile = self.config["VAULT_PROFILES"][0]
            if self.config.get("SHOW_DETAILS_ON_STARTUP", False):
                QTimer.singleShot(10, self.toggle_details)

        # Automatically start the first backup when the app launches.
        if run_backup_on_startup:
            self.run_backup_process()
        else:
            self._update_ui_for_idle_state()

    def showEvent(self, event):
        """Called when the main window is shown for the first time."""
        super().showEvent(event)
        # If this is the very first run (no config file), open settings now.
        # This ensures the main window has a valid geometry for centering.
        if self.is_first_run:
            self.open_settings()
            self.is_first_run = False # Prevent it from running again.
    
    def highlight_settings_button(self):
        """Applies a stylesheet to draw attention to the settings button."""
        self.settings_button.setStyleSheet("QToolButton { border: 3px solid #FFC107; border-radius: 8px; }")

    def unhighlight_settings_button(self):
        """Removes the highlight stylesheet from the settings button."""
        self.settings_button.setStyleSheet("")

    @Slot()
    def open_settings(self):
        """Creates and shows the settings window."""
        self.unhighlight_settings_button()

        # If the auto-close timer is running, cancel it before opening settings.
        if self.close_timer.isActive():
            self.cancel_auto_close()

        # The check must be for None, because an empty dictionary ({}) is a valid
        # state on first run, but evaluates to False in a boolean context.
        if self.config is None:
            self.status_label.setText("Cannot open settings: Configuration not loaded.")
            return

        # Create the window if it doesn't exist, or bring it to the front if it does.
        if self.settings_window is None or not self.settings_window.isVisible():
            self.settings_window = SettingsWindow(self.config, self)
            self.settings_window.settings_saved.connect(self.on_settings_saved)
            self.settings_window.quit_requested.connect(self.quit_application)

        # Manually center the settings window on the main window before showing it.
        # This is more reliable than using showEvent for dialog-like windows.
        parent_rect = self.geometry()
        self.settings_window.move(parent_rect.center() - self.settings_window.rect().center())

        self.settings_window.show()
        self.settings_window.activateWindow() # Bring to front
    
    @Slot()
    def run_backup_process(self):
        """Sets up and starts the backup worker thread."""
        self.is_backup_running = True

        self.close_timer.stop()
        self.close_button.setText("Close")

        self.action_button_widget.setVisible(False)

        # Change close button to Stop button during backup
        self.close_button.setText("Stop")
        self.close_button.setEnabled(True)
        self.backup_button.setVisible(False) # Hide the "Try Again" button when a run starts

        # --- Pre-flight check for sudo password ---
        sudo_password = None
        # Use the new utility function to check the state
        if is_password_required():
            password, ok = QInputDialog.getText(
                self, "System Password Required",
                "Please enter your sudo password to mount the VeraCrypt vault:",
                QLineEdit.Password
            )
            if not ok:  # User cancelled
                # Reset the UI to its idle state before returning
                self.close_button.setEnabled(True)
                self.backup_button.setVisible(True)
                return

            # Verify the password before proceeding to avoid passing a bad password
            # to the worker thread, which can cause complex failures.
            if not verify_sudo_password(password):
                QMessageBox.warning(self, "Incorrect Password", "The system password you entered was incorrect. Backup aborted.")
                self.close_button.setEnabled(True)
                self.backup_button.setVisible(True)
                return

            sudo_password = password
        else:
            # Passwordless sudo is configured, so we pass an empty string to the worker.
            sudo_password = ""

        self.last_sudo_password = sudo_password
        self.log_box.clear()
        self.status_label.setText("Starting backup process...")
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)

        if not self.config:
            # Config failed to load in __init__, so we can't proceed.
            return # Error is already displayed.

        self._update_info_labels()

        # Set running status
        self.update_main_status(StatusCodes.RUNNING)
        self.thread = QThread()
        self.worker = BackupWorker(self.config, self.current_profile, sudo_password=sudo_password)

        self.worker.moveToThread(self.thread)

        # Connect worker signals to GUI slots
        self.worker.log_message.connect(self.append_log)
        self.worker.step_changed.connect(self.on_step_changed)
        self.worker.status_update.connect(self.update_status)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.main_status_changed.connect(self.update_main_status)
        self.worker.finished.connect(self.on_worker_finished)

        # Connect thread signals
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        # Connect stop button functionality during backup
        try:
            self.close_button.clicked.disconnect()
        except RuntimeError:
            pass # Already disconnected
        self.close_button.clicked.connect(self.on_stop_clicked)

        self.thread.start()


    @Slot(str)
    def on_step_changed(self, step_name):
        """Keeps track of the worker's current step."""
        self.current_backup_step = step_name

    @Slot()
    def on_settings_saved(self):
        """Called when settings are saved or imported to refresh the UI."""
        self.config, error_msg = load_config()
        if error_msg:
            self.update_main_status(StatusCodes.CONFIG_ERROR, f"Failed to reload config: {error_msg}")
            return

        self.current_profile = self.config["VAULT_PROFILES"][0]
        self._update_info_labels()
        self.backup_button.setVisible(True)
        self.update_main_status(StatusCodes.IDLE, "Configuration updated. Click 'Backup' to start.")

    def _update_info_labels(self):
        """Reads from the config and updates the main window's info labels."""
        if not self.current_profile:
            return

        vault_relative_path = self.current_profile.get("VERACRYPT_VAULT", "N/A")
        vault_name = os.path.basename(vault_relative_path)
        self.vault_info_label.setProperty("vault_name", vault_name) # Store for styling
        gdrive_dir = self.config.get("GOOGLE_DRIVE_BACKUP_DIR", "N/A")

        # Get and format the vault size
        vault_full_path = os.path.join(os.path.expanduser('~'), vault_relative_path)
        vault_size_str = ""
        if os.path.exists(vault_full_path):
            try:
                size_bytes = os.path.getsize(vault_full_path)
                if size_bytes > 1024 * 1024 * 1024: # GB
                    size_str = f"{size_bytes / (1024**3):.2f} GB"
                elif size_bytes > 1024 * 1024: # MB
                    size_str = f"{size_bytes / (1024**2):.2f} MB"
                else: # KB
                    size_str = f"{size_bytes / 1024:.2f} KB"
                vault_size_str = f" ({size_str})"
            except OSError:
                vault_size_str = "" # Fail silently on permission errors etc.
        
        self.vault_info_label.setProperty("vault_size", vault_size_str) # Store for styling
        self._apply_vault_label_style() # Apply default (unmounted) style
        self.dest_info_label.setText(f"to: Google Drive / {gdrive_dir}")

    @Slot()
    def toggle_details(self):
        """Shows or hides the detailed log panel."""
        is_hidden = self.details_panel.isHidden()
        self.details_panel.setVisible(is_hidden)
        if is_hidden:
            self.toggle_details_button.setArrowType(Qt.UpArrow)
            self.toggle_details_button.setText("Hide Details")
            self.setFixedSize(1200, 450 + 400) # control_panel + details_panel height
        else:
            self.toggle_details_button.setArrowType(Qt.DownArrow)
            self.toggle_details_button.setText("Show Details")
            self.setFixedSize(1200, 450) # control_panel height only

        # Save the new state to the config file
        if self.config:
            self.config['SHOW_DETAILS_ON_STARTUP'] = is_hidden
            save_config(self.config)

    @Slot(str)
    def append_log(self, message):
        """Appends a message to the log box."""
        self.log_box.appendPlainText(message)

    def get_status_info(self, status_code, details=""):
        """Maps status codes to user-friendly messages and styles."""
        # Define colors
        COLOR_GREEN = "#4CAF50"
        COLOR_ORANGE = "#FFA000"
        COLOR_RED = "#D32F2F"

        status_map = {
            # Positive/Neutral States
            StatusCodes.IDLE: {
                'status': "IDLE", 'color': COLOR_GREEN,
                'detail': details or "Click 'Backup' to start."
            },
            StatusCodes.NEEDS_CONFIG: {
                'status': "NEEDS CONFIG", 'color': COLOR_ORANGE,
                'detail': "Welcome! Please configure the application to begin."
            },
            StatusCodes.RUNNING: {
                'status': "RUNNING", 'color': COLOR_ORANGE,
                'detail': "Backup in progress..."
            },
            StatusCodes.COMPLETE: {
                'status': "COMPLETE", 'color': COLOR_GREEN,
                'detail': "All operations complete."
            },
            StatusCodes.STOPPED: {
                'status': "STOPPED", 'color': COLOR_ORANGE,
                'detail': "Backup was stopped by user request."
            },
            # Error States
            StatusCodes.CONFIG_ERROR: {
                'status': "CONFIG ERROR", 'color': COLOR_RED,
                'detail': f"Configuration Error: {details}"
            },
            StatusCodes.GDRIVE_NOT_MOUNTED: {
                'status': "Error: Google Drive Not Mounted?", 'color': COLOR_RED,
                'detail': "The path is not responding. Please check that Google Drive is mounted."
            },
            StatusCodes.GDRIVE_WRITE_FAILED: {
                'status': "Error: Failed to write to Google Drive", 'color': COLOR_RED,
                'detail': "A file operation failed. Check permissions and path in the details log."
            },
            StatusCodes.PERMISSION_DENIED: {
                'status': "Error: Permission Denied", 'color': COLOR_RED,
                'detail': "Access was denied. Check file/folder permissions."
            },
            StatusCodes.DISK_FULL: {
                'status': "Error: Disk Full", 'color': COLOR_RED,
                'detail': "Insufficient disk space to complete the operation."
            },
            StatusCodes.NETWORK_ERROR: {
                'status': "Error: Network Issue", 'color': COLOR_RED,
                'detail': "Network connection failed. Check your internet connection."
            },
            StatusCodes.VERIFICATION_FAILED: {
                'status': "Error: Verification Failed", 'color': COLOR_RED,
                'detail': "The remote file is corrupt. The backup will be attempted again on the next run."
            },
            StatusCodes.GENERAL_ERROR: {
                'status': "ERROR", 'color': COLOR_RED,
                'detail': f"CRITICAL ERROR: {details}" if details else "An unexpected error occurred."
            }
        }
        return status_map.get(status_code, status_map[StatusCodes.GENERAL_ERROR])

    @Slot(str)
    def update_status(self, text):
        """Updates the main status label and appends to the log."""
        self.status_label.setText(text)
        self.log_box.appendPlainText(f"--- {text}")
    
    @Slot(int)
    def update_progress(self, percentage):
        """Updates the progress bar with the given percentage."""
        if not self.progress_bar.isVisible():
            self.progress_bar.setVisible(True)
        self.progress_bar.setValue(percentage)

    @Slot()
    def update_main_status(self, status_code, details=""):
        """The single point of truth for updating the main status labels and color."""
        self.last_status_code = status_code
        status_info = self.get_status_info(status_code, details)
        
        self.running_status_label.setText(status_info['status'])
        self.running_status_label.setStyleSheet(f"background-color: {status_info['color']}; color: white; border-radius: 5px;")
        self.status_label.setText(status_info['detail'])

        # Also log critical errors
        is_error = status_info['color'] == "#D32F2F"
        if is_error:
            log_text = details if details else status_info['detail']
            self.log_box.appendPlainText(f"\n--- CRITICAL ERROR ---\n{log_text}")

    @Slot()
    def on_worker_finished(self):
        """
        Called when the worker thread has finished. This is the single source of truth
        for UI state changes after a run (e.g., enabling/disabling buttons).
        """
        self.is_backup_running = False

        # If a quit was requested, just close the app and skip all other UI updates.
        if hasattr(self, '_close_on_finish') and self._close_on_finish:
            self.close()
            return

        self.close_button.setEnabled(True)
        # Hide progress bar when backup finishes
        self.progress_bar.setVisible(False)
        # Disconnect any temporary handlers (like for auto-close) and reconnect the default.
        try:
            self.close_button.clicked.disconnect()
        except RuntimeError:
            pass # It might have been disconnected already

        # The status text and color are already set by update_main_status.
        # We just need to manage the buttons and auto-close timer.
        if self.last_status_code == StatusCodes.COMPLETE:
            self.backup_button.setVisible(False) # No need for "Try Again" on success.
            self.countdown_seconds = self.config.get("AUTO_CLOSE_SECONDS", 5)
            # Only start the countdown if it's enabled AND the settings window is not open.
            if isinstance(self.countdown_seconds, int) and self.countdown_seconds > 0 and (not self.settings_window or not self.settings_window.isVisible()):
                self.close_button.setText(f"Do Not Close ({self.countdown_seconds})")
                self.close_button.clicked.connect(self.cancel_auto_close)
                self.close_timer.start(1000) # 1000 ms = 1 second
            else:
                self.close_button.setText("Close")
                self.close_button.clicked.connect(self.close)
        else:
            # This covers STOPPED and all ERROR cases.
            self.backup_button.setVisible(True) # Show the "Try Again" button.
            self.close_button.setText("Close")
            self.close_button.clicked.connect(self.close)

        # This is the crucial part: This is called ONCE, after the backup thread is finished.
        # It will start a new, short-lived thread to check the vault status.
        self._update_ui_for_idle_state(sudo_password=self.last_sudo_password)
        self.last_sudo_password = None # Clear after use

    @Slot()
    def update_countdown(self):
        """Updates the close button timer each second."""
        self.countdown_seconds -= 1
        if self.countdown_seconds > 0:
            self.close_button.setText(f"Do Not Close ({self.countdown_seconds})")
        else:
            self.close_timer.stop()
            self.close()

    @Slot()
    def on_stop_clicked(self):
        """Handles the Stop button click during backup."""
        if hasattr(self, 'worker') and self.worker:
            self.worker.request_cancellation()
            self.close_button.setText("Stopping...")
            self.close_button.setEnabled(False)
            self.log_box.appendPlainText("\n--- STOP REQUESTED ---\nBackup will stop at the next safe point...")

    @Slot()
    def cancel_auto_close(self):
        """Stops the auto-close timer and reverts the button to a normal 'Close' button."""
        self.close_timer.stop()
        self.close_button.setText("Close")
        try:
            self.close_button.clicked.disconnect()
        except RuntimeError:
            pass
        self.close_button.clicked.connect(self.close)

    def close(self):
        """Stops any running timers and closes the application."""
        self.close_timer.stop()
        super().close()

    @Slot()
    def quit_application(self):
        """Stops the backup if it's running, then closes the application."""
        if self.is_backup_running:
            # A backup is running. Request cancellation and set a flag to close when it's done.
            self._close_on_finish = True
            self.worker.request_cancellation()
            self.close_button.setText("Quitting...")
            self.close_button.setEnabled(False)
            self.log_box.appendPlainText("\n--- QUIT REQUESTED ---\nBackup will stop at the next safe point, then the application will close.")
        else:
            # No backup running, just close immediately.
            self.close()

    def _get_sudo_password_if_needed(self):
        """Prompts for sudo password if passwordless is not enabled. Returns password or None."""
        if is_password_required():
            password, ok = QInputDialog.getText(
                self, "System Password Required",
                "Please enter your sudo password for this VeraCrypt action:",
                QLineEdit.Password
            )
            if not ok:
                return None # User cancelled
            return password
        return "" # Passwordless is enabled, return empty string for the worker

    def _run_vault_action(self, mode, sudo_password=None):
        """Generic method to run a VaultActionWorker task."""
        # If no password was passed in, try to get one.
        if sudo_password is None:
            sudo_password = self._get_sudo_password_if_needed()

        if sudo_password is None: # This means the user cancelled the password dialog
            return

        self.mount_button.setEnabled(False)
        self.empty_vault_button.setEnabled(False)

        thread = QThread()
        worker = VaultActionWorker(self.config, self.current_profile, sudo_password)
        worker.moveToThread(thread)

        worker.log_message.connect(self.append_log)
        worker.status_updated.connect(self._on_vault_status_updated)
        worker.finished.connect(lambda: self.mount_button.setEnabled(True))
        worker.finished.connect(lambda: self.empty_vault_button.setEnabled(True))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.started.connect(lambda: worker.run(mode))
        thread.start()
        # Keep a reference to the thread to prevent it from being garbage collected
        self.action_thread = thread

    def _update_ui_for_idle_state(self, sudo_password=None):
        """Shows action buttons and triggers a status check."""
        self.action_button_widget.setVisible(True)
        self._run_vault_action("CHECK_STATUS", sudo_password=sudo_password)

    @Slot()
    def on_mount_button_clicked(self):
        self._run_vault_action("TOGGLE_MOUNT")

    @Slot()
    def on_empty_vault_button_clicked(self):
        reply = QMessageBox.warning(
            self, "Confirm Empty Vault",
            "This will permanently delete all files and folders inside the mounted VeraCrypt vault.\n\n"
            "This is useful for reclaiming space if you have removed items from your backup list, but it cannot be undone.\n\n"
            "Are you sure you want to proceed?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel
        )
        if reply == QMessageBox.Yes:
            self._run_vault_action("EMPTY_VAULT")

    @Slot(bool)
    def _on_vault_status_updated(self, is_mounted):
        """Updates the mount button and vault name style based on the vault's status."""
        self._apply_vault_label_style(is_mounted)
        if is_mounted:
            self.mount_button.setText("Unmount")
            self.empty_vault_button.setEnabled(True)
        else:
            self.mount_button.setText("Mount")
            self.empty_vault_button.setEnabled(False)

    def _apply_vault_label_style(self, is_mounted=False):
        """Applies rich text styling to the vault name label."""
        vault_name = self.vault_info_label.property("vault_name") or ""
        vault_size = self.vault_info_label.property("vault_size") or ""
        if is_mounted:
            html = f"Crypt: <span style='color: #2E7D32; font-weight: bold;'>{vault_name}{vault_size}</span>"
            self.vault_info_label.setText(html)
        else:
            self.vault_info_label.setText(f"Crypt: {vault_name}{vault_size}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
