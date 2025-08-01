import os
import subprocess
import shutil

from PySide2.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QHBoxLayout,
                               QLabel, QToolButton, QStyle, QFormLayout, QLineEdit,
                               QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
                               QFrame, QListView, QTreeView,
                               QAbstractItemView, QCheckBox, QInputDialog, QSlider, QFrame)
from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QFont, QIntValidator, QColor

from config_utils import save_config
from settings_io import export_settings_to_file, import_settings_from_file
from sudo_utils import is_password_required, setup_passwordless_sudo, remove_passwordless_sudo
from credentials_manager import get_veracrypt_password, set_veracrypt_password, delete_veracrypt_password
from veracrypt_utils import test_credentials

class SettingsWindow(QWidget):
    """A new window for application settings."""
    # Signal to notify the main window that settings have been saved
    settings_saved = Signal()
    quit_requested = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        # This is the crucial fix: Tell Qt to treat this widget as a separate window, not a child component.
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(1200)

        self.config = config
        # For now, we will always edit the first profile in the list.
        if "VAULT_PROFILES" in self.config and self.config["VAULT_PROFILES"]:
            self.profile = self.config["VAULT_PROFILES"][0]
        else:
            # This is a fallback for a brand new, empty config.
            # Create a dummy profile to avoid crashing the UI.
            self.profile = {"ID": "", "NAME": "New Profile", "VERACRYPT_VAULT": "", "BACKUP_DIRS": []}
            if "VAULT_PROFILES" not in self.config:
                self.config["VAULT_PROFILES"] = []
            self.config["VAULT_PROFILES"].append(self.profile)

        self.initial_vault_path = self.profile.get("VERACRYPT_VAULT", "")
        self.initial_password = get_veracrypt_password(self.initial_vault_path)
        self.initial_ask_for_password_state = is_password_required()

        main_layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignRight)

        # --- Profile Name (Hidden for now, will be used for multi-vault support) ---
        # self.profile_name_edit = QLineEdit(self.profile.get("NAME", "Default Profile"))
        width_32_chars = self.fontMetrics().horizontalAdvance('W' * 32)
        # self.profile_name_edit.setFixedWidth(width_32_chars)
        # self.profile_name_edit.setToolTip("A friendly name for this backup profile.")

        # --- VeraCrypt Vault Path with File Selector ---
        self.vault_path_edit = QLineEdit(self.profile.get("VERACRYPT_VAULT", ""))
        # Calculate a fixed width based on a 32-character string
        self.vault_path_edit.setFixedWidth(width_32_chars)
        vault_select_button = QToolButton()
        vault_select_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        vault_select_button.setToolTip("Select VeraCrypt Vault File")
        vault_select_button.clicked.connect(self.select_vault_file)

        vault_path_layout = QHBoxLayout()
        vault_path_layout.setContentsMargins(0,0,0,0) # Ensure it fits snugly
        vault_path_layout.addWidget(self.vault_path_edit)
        vault_path_layout.addWidget(vault_select_button)

        # --- Password with visibility toggle and test button ---
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setFixedWidth(width_32_chars)

        # Check if a password exists in the keyring for the current vault
        if self.initial_password:
            self.password_edit.setText(self.initial_password)
            self.password_edit.setPlaceholderText("Password loaded from keyring.")
        else:
            self.password_edit.setPlaceholderText("Enter new password here.")

        password_layout = QHBoxLayout()
        password_layout.setContentsMargins(0,0,0,0)

        toggle_visibility_button = QToolButton()
        toggle_visibility_button.setText("👁️") # This emoji works on most modern systems
        toggle_visibility_button.setToolTip("Toggle password visibility")
        toggle_visibility_button.clicked.connect(self.toggle_password_visibility)

        self.test_button = QPushButton("Test")
        self.test_button.setToolTip("Test the vault path and password")
        self.test_button.clicked.connect(self.test_veracrypt_credentials)

        password_layout.addWidget(self.password_edit)
        password_layout.addWidget(toggle_visibility_button)
        password_layout.addWidget(self.test_button)

        # --- Backup Directories List ---
        backup_dirs_widget = QWidget()
        backup_dirs_layout = QVBoxLayout(backup_dirs_widget)
        backup_dirs_layout.setContentsMargins(0,0,0,0)
        self.backup_dirs_list = QListWidget()
        self.backup_dirs_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for directory in self.profile.get("BACKUP_DIRS", []):
            self.backup_dirs_list.addItem(QListWidgetItem(directory))
        backup_dirs_layout.addWidget(self.backup_dirs_list)

        add_remove_layout = QHBoxLayout()
        add_button = QPushButton("Add Directories...")
        remove_button = QPushButton("Remove Selected")
        add_remove_layout.addStretch()
        add_remove_layout.addWidget(add_button)
        add_remove_layout.addWidget(remove_button)
        backup_dirs_layout.addLayout(add_remove_layout)

        # --- Other input fields ---
        self.gdrive_path_edit = QLineEdit(self.config.get("GOOGLE_DRIVE_PATH", ""))

        gdrive_path_detect_button = QPushButton("Detect...")
        gdrive_path_detect_button.setToolTip("Attempt to auto-detect mounted Google Drive paths")
        gdrive_path_detect_button.clicked.connect(self.detect_gdrive_paths)

        gdrive_path_layout = QHBoxLayout()
        gdrive_path_layout.setContentsMargins(0,0,0,0)
        gdrive_path_layout.addWidget(self.gdrive_path_edit, 1) # Give the line edit more stretch
        gdrive_path_layout.addWidget(gdrive_path_detect_button)


        self.gdrive_dir_edit = QLineEdit(self.config.get("GOOGLE_DRIVE_BACKUP_DIR", ""))
        self.gdrive_dir_edit.setFixedWidth(width_32_chars)
        gdrive_dir_select_button = QToolButton()
        gdrive_dir_select_button.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        gdrive_dir_select_button.setToolTip("Select Google Drive Backup Folder")
        gdrive_dir_select_button.clicked.connect(self.select_gdrive_folder)

        gdrive_dir_layout = QHBoxLayout()
        gdrive_dir_layout.setContentsMargins(0,0,0,0)
        gdrive_dir_layout.addWidget(self.gdrive_dir_edit)
        gdrive_dir_layout.addWidget(gdrive_dir_select_button)

        self.autoclose_edit = QLineEdit(str(self.config.get("AUTO_CLOSE_SECONDS", 5)))
        self.autoclose_edit.setToolTip("How long the program will wait to close after sucessful backup. Set to 0 to disable auto-close.")
        self.autoclose_edit.setValidator(QIntValidator(0, 999, self))
        # Set width based on 3 'W' characters plus some padding
        width_3_chars = self.fontMetrics().horizontalAdvance('W' * 3) + 10
        self.autoclose_edit.setFixedWidth(width_3_chars)
        self.autoclose_edit.setAlignment(Qt.AlignRight)

        # --- Network Connection Quality (compact) ---
        self.network_quality_slider = QSlider(Qt.Horizontal)
        self.network_quality_slider.setMinimum(0)
        self.network_quality_slider.setMaximum(2)
        self.network_quality_slider.setValue(self.config.get("NETWORK_QUALITY", 0))
        self.network_quality_slider.setTickPosition(QSlider.TicksBelow)
        self.network_quality_slider.setTickInterval(1)
        self.network_quality_slider.setFixedWidth(80)  # Make slider shorter to leave more room
        
        self.network_quality_label = QLabel()
        self.update_network_quality_label(self.network_quality_slider.value())
        self.network_quality_slider.valueChanged.connect(self.update_network_quality_label)
        
        # Set fixed width for the label to accommodate different text lengths
        self.network_quality_label.setFixedWidth(140)  # Wider to prevent text being hidden
        self.network_quality_label.setAlignment(Qt.AlignRight)
        
        # Create framed network quality widget
        network_frame = QFrame()
        network_frame.setFrameStyle(QFrame.Box | QFrame.Plain)
        network_frame.setLineWidth(1)
        network_frame.setToolTip("Increases the timeout for slower networks. Terrible=never times out")
        network_frame_layout = QHBoxLayout(network_frame)
        network_frame_layout.setContentsMargins(5, 2, 5, 2)
        network_frame_layout.addWidget(QLabel("Network Quality:"))
        network_frame_layout.addWidget(self.network_quality_slider)
        network_frame_layout.addSpacing(8)  # Add space between slider and description
        network_frame_layout.addWidget(self.network_quality_label)
        
        # Create combined layout for auto-close and network quality
        autoclose_network_layout = QHBoxLayout()
        autoclose_network_layout.setContentsMargins(0, 0, 0, 0)
        autoclose_network_layout.addWidget(self.autoclose_edit)
        autoclose_network_layout.addStretch()  # Push network frame to the right
        autoclose_network_layout.addWidget(network_frame)
        autoclose_network_layout.addStretch()

        self.ask_password_checkbox = QCheckBox("Always ask for system password.")
        self.ask_password_checkbox.setChecked(self.initial_ask_for_password_state)
        self.ask_password_checkbox.setToolTip("If checked, you will be prompted for your sudo password for each backup.\nIf unchecked, a passwordless sudo rule will be created for VeraCrypt.")

        self.auto_mount_checkbox = QCheckBox("Auto-mount Google Drive if not accessible.")
        self.auto_mount_checkbox.setChecked(self.config.get("AUTO_MOUNT_GDRIVE", True))
        self.auto_mount_checkbox.setToolTip("If checked, the backup will attempt to automatically mount Google Drive when it's not accessible.\nThis may prompt for authentication in your desktop environment.")

        backup_dirs_label = QLabel("To Backup:")
        backup_dirs_label.setToolTip("Paths are stored relative to your home directory (~).")

        #let's keep the names short here, and trust in the user to understand them.
        # form_layout.addRow("Profile Name:", self.profile_name_edit)
        form_layout.addRow("VeraCrypt Vault:", vault_path_layout)
        form_layout.addRow("Password:", password_layout)
        form_layout.addRow(backup_dirs_label, backup_dirs_widget)
        form_layout.addRow("GDrive Path:", gdrive_path_layout)
        form_layout.addRow("GDrive Folder:", gdrive_dir_layout)
        form_layout.addRow("Auto-Close(sec):", autoclose_network_layout)
        form_layout.addRow("", self.ask_password_checkbox)
        form_layout.addRow("", self.auto_mount_checkbox)

        # Create Save and Cancel buttons
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")

        # Create Import and Export buttons
        self.import_button = QPushButton("Import Settings...")
        self.export_button = QPushButton("Export Settings...")

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.import_button)
        button_layout.addWidget(self.export_button)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)

        main_layout.addLayout(form_layout)
        main_layout.addStretch()
        main_layout.addLayout(button_layout)

        # Connect signals
        self.save_button.clicked.connect(self.save_and_close)
        self.cancel_button.clicked.connect(self.close)
        add_button.clicked.connect(self.add_backup_directories)
        remove_button.clicked.connect(self.remove_backup_directory)
        self.import_button.clicked.connect(self.on_import_clicked)
        self.export_button.clicked.connect(self.on_export_clicked)

    def showEvent(self, event):
        """Called whenever the window is shown, to refresh UI elements."""
        super().showEvent(event)
        # Refresh highlights every time the window is shown to ensure consistency.
        self._refresh_list_highlights()
        
    def keyPressEvent(self, event):
        """Handles key presses for the settings window."""
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_Q and event.modifiers() == Qt.ControlModifier:
            self.quit_requested.emit()
        else:
            super().keyPressEvent(event)

    def update_network_quality_label(self, value):
        """Updates the network quality label based on slider value."""
        if value == 0:
            text = "(Good)"
            tooltip = "Good network connection - normal timeouts"
        elif value == 1:
            text = "(Poor)"
            tooltip = "Poor network connection - extended timeouts (3x normal)"
        else:  # value == 2
            text = "(Terrible)"
            tooltip = "Terrible network connection - no timeouts (wait indefinitely)"
        
        self.network_quality_label.setText(text)
        self.network_quality_label.setToolTip(tooltip)

    # --- Helper Methods ---
    def _refresh_list_highlights(self):
        """Iterates through the backup list and applies highlighting to external directories."""
        home_dir = os.path.expanduser('~')
        for i in range(self.backup_dirs_list.count()):
            item = self.backup_dirs_list.item(i)
            relative_path = item.text()
            # Resolve the path to an absolute path to reliably check if it's outside home.
            full_path = os.path.abspath(os.path.join(home_dir, relative_path))

            is_external = not full_path.startswith(home_dir)

            if is_external:
                # Use a brighter orange as requested.
                item.setBackground(QColor("#F29E1F"))
                item.setToolTip("This directory is outside your home folder and may cause backup errors.")
            else:
                # Explicitly remove background color for non-external items.
                item.setBackground(QColor(Qt.transparent))
                item.setToolTip("")

    def handle_sudoers_change(self):
        """Called on save to manage the sudoers file if the checkbox state changed."""
        new_state_is_password_required = self.ask_password_checkbox.isChecked()

        if new_state_is_password_required == self.initial_ask_for_password_state:
            return  # No change, do nothing.

        if new_state_is_password_required:
            # User wants to be asked for a password, so we must remove the file.
            if not remove_passwordless_sudo(self):
                # If removal fails, revert the checkbox to its original state
                self.ask_password_checkbox.setChecked(self.initial_ask_for_password_state)
        else:
            # User wants passwordless, so we must create the file.
            if not setup_passwordless_sudo(self):
                # If setup fails, revert the checkbox
                self.ask_password_checkbox.setChecked(self.initial_ask_for_password_state)

    # --- Slots / Event Handlers ---
    def save_and_close(self):
        """Update the config dictionary, save it to file, and close the window."""
        self.handle_sudoers_change()

        # Collect backup directories from the list widget
        backup_dirs = []
        for i in range(self.backup_dirs_list.count()):
            backup_dirs.append(self.backup_dirs_list.item(i).text())
        self.profile["BACKUP_DIRS"] = backup_dirs

        # --- Handle Password and Vault Path Changes ---
        new_vault_path = self.vault_path_edit.text()
        new_password = self.password_edit.text()

        # If the vault path has changed, we must delete the old password from the keyring.
        if self.initial_vault_path and self.initial_vault_path != new_vault_path:
            delete_veracrypt_password(self.initial_vault_path)

        # Determine if we should save the password based on whether it has changed.
        should_save_password = False
        if self.initial_password is not None:
            # A password existed. Save if it's different from the original.
            if new_password != self.initial_password:
                should_save_password = True
        else:
            # No password existed. Only save if the user actually entered one.
            if new_password:
                should_save_password = True

        if should_save_password:
            success, error_msg = set_veracrypt_password(new_vault_path, new_password)
            if not success:
                QMessageBox.critical(self, "Keyring Error", f"Could not save password to system keyring:\n\n{error_msg}")
                # Do not close the window on a critical save error
                return

        self.profile["VERACRYPT_VAULT"] = new_vault_path
        # The profile name is not editable for now, so we don't update it.
        # self.profile["NAME"] = self.profile_name_edit.text()

        self.config["GOOGLE_DRIVE_PATH"] = self.gdrive_path_edit.text()
        self.config["GOOGLE_DRIVE_BACKUP_DIR"] = self.gdrive_dir_edit.text()

        try:
            autoclose_val = int(self.autoclose_edit.text())
        except (ValueError, TypeError):
            autoclose_val = 0 # Default to 0 if empty or invalid
        self.config["AUTO_CLOSE_SECONDS"] = autoclose_val
        
        # Save network quality setting
        self.config["NETWORK_QUALITY"] = self.network_quality_slider.value()

        # Save checkbox states
        self.config["AUTO_MOUNT_GDRIVE"] = self.auto_mount_checkbox.isChecked()

        # Ensure the password key is removed from the config dictionary before saving.
        self.config.pop("VERACRYPT_PASSWORD", None)

        # Ensure these keys exist on first save or for legacy configs
        if 'SHOW_DETAILS_ON_STARTUP' not in self.config:
            self.config['SHOW_DETAILS_ON_STARTUP'] = False
        if 'WARN_ON_EXTERNAL_DIR' not in self.config:
            self.config['WARN_ON_EXTERNAL_DIR'] = True
        if 'CONFIG_VER' not in self.config:
            self.config['CONFIG_VER'] = 1

        save_config(self.config)
        self.settings_saved.emit()
        self.close()

    def on_export_clicked(self):
        """Handles the export button click by calling the external function."""
        export_settings_to_file(self)

    def on_import_clicked(self):
        """Handles the import button click and reloads settings on success."""
        success = import_settings_from_file(self)
        if success:
            self.settings_saved.emit()
            self.close()

    def remove_backup_directory(self):
        """Removes the currently selected directory from the backup list."""
        selected_items = self.backup_dirs_list.selectedItems()
        if not selected_items:
            return # Nothing selected, so do nothing.
        for item in selected_items:
            self.backup_dirs_list.takeItem(self.backup_dirs_list.row(item))

    def add_backup_directories(self):
        """
        Opens a dialog that allows selecting multiple directories.
        """
        home_dir = os.path.expanduser('~')
        documents_dir = os.path.join(home_dir, 'Documents')
        start_dir = documents_dir if os.path.isdir(documents_dir) else home_dir

        dialog = QFileDialog(self, "Select Directories to Backup", start_dir)
        dialog.setFileMode(QFileDialog.Directory)
        dialog.resize(1024, 1024)
        
        # This is the key trick to enable multi-selection of directories
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        
        # Find the list view and enable extended selection
        list_view = dialog.findChild(QListView, 'listView')
        if list_view:
            list_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        
        # Find the tree view and enable extended selection
        tree_view = dialog.findChild(QTreeView)
        if tree_view:
            tree_view.setSelectionMode(QAbstractItemView.ExtendedSelection)

        if not dialog.exec_():
            return

        selected_dirs = dialog.selectedFiles()
        if not selected_dirs:
            return

        # --- Process selected paths ---
        existing_items = {self.backup_dirs_list.item(i).text() for i in range(self.backup_dirs_list.count())}

        paths_to_add = []
        external_paths_to_warn = []

        for dir_path in sorted(list(selected_dirs)):
            relative_path = os.path.relpath(dir_path, home_dir)
            if relative_path in existing_items:
                continue  # Skip duplicates

            is_external = not os.path.abspath(dir_path).startswith(home_dir)
            if is_external:
                external_paths_to_warn.append(relative_path)
            else:
                paths_to_add.append(relative_path)

        # --- Handle warnings for external paths in a single dialog ---
        warn_on_external = self.config.get("WARN_ON_EXTERNAL_DIR", True)
        if external_paths_to_warn and warn_on_external:
            path_list_str = "\n".join([f"  - {p}" for p in external_paths_to_warn])
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.NoIcon)
            msg_box.setWindowTitle("External Directory Warning")
            msg_box.setText(f"The following selected directories are outside your home folder:\n\n{path_list_str}\n\n"
                            "Backing up system directories can be slow and may include files you don't have permission to read, causing errors.\n\n")
            never_warn_checkbox = QCheckBox("Don't warn me about this again")
            msg_box.setCheckBox(never_warn_checkbox)
            add_button = msg_box.addButton("Add", QMessageBox.YesRole)
            msg_box.addButton("Cancel", QMessageBox.NoRole)
            msg_box.setDefaultButton(add_button)
            msg_box.setStyleSheet("QLabel{min-width: 1000px; padding-right: 15px;}")
            msg_box.exec_()

            if never_warn_checkbox.isChecked():
                self.config["WARN_ON_EXTERNAL_DIR"] = False

            if msg_box.clickedButton() == add_button:
                paths_to_add.extend(external_paths_to_warn)

        # --- Add all approved paths to the list widget ---
        for relative_path in paths_to_add:
            item = QListWidgetItem(relative_path)
            self.backup_dirs_list.addItem(item)
        self._refresh_list_highlights()

    def toggle_password_visibility(self):
        """Toggles the password field between visible and hidden."""
        if self.password_edit.echoMode() == QLineEdit.Password:
            self.password_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)
    
    def test_veracrypt_credentials(self):
        """Runs 'veracrypt --test' to verify the vault path and password."""
        vault_relative_path = self.vault_path_edit.text().strip()
        password_to_test = self.password_edit.text()

        if not vault_relative_path or not password_to_test:
            QMessageBox.warning(self, "Missing Information",
                                "Please provide both the VeraCrypt Vault path and the password to run a test.")
            return

        home_dir = os.path.expanduser('~')
        full_vault_path = os.path.join(home_dir, vault_relative_path)

        # Disable button during the test and force the UI to update
        self.test_button.setEnabled(False)
        self.test_button.setText("Testing...")
        QApplication.processEvents()

        try:
            # Call the new utility function which handles the command execution
            success, message = test_credentials(full_vault_path, password_to_test)

            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.NoIcon)
            msg_box.setText(message)
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.setStyleSheet("QLabel{min-width: 450px;}")

            if success:
                msg_box.setWindowTitle("Success")
            else:
                msg_box.setWindowTitle("Test Failed")
            msg_box.exec_()
        finally:
            # Always re-enable the button
            self.test_button.setEnabled(True)
            self.test_button.setText("Test")

    def select_vault_file(self):
        """Opens a file dialog to select the VeraCrypt vault file."""
        home_dir = os.path.expanduser('~')
        current_relative_path = self.vault_path_edit.text()

        start_dir = ""
        if current_relative_path:
            # Construct full path to get its directory
            full_current_path = os.path.join(home_dir, current_relative_path)
            start_dir = os.path.dirname(full_current_path)

        # Fallback if path is empty or directory doesn't exist
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = os.path.join(home_dir, 'Documents')
            # Final fallback to home if Documents doesn't exist
            if not os.path.isdir(start_dir):
                start_dir = home_dir
        
        dialog = QFileDialog(
            self,
            "Select VeraCrypt Vault File",
            start_dir,
            "All Files (*)"
        )
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.resize(1024, 768)

        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            if selected_files:
                file_path = selected_files[0]

                # Warn the user about large vault file sizes
                try:
                    file_size_bytes = os.path.getsize(file_path)

                    # Define size thresholds (bytes)
                    SIZE_100MB = 100 * (1024**2)
                    SIZE_400MB = 400 * (1024**2)
                    SIZE_1GB = 1 * (1024**3)

                    # Determine the warning level
                    user_level = 0
                    if file_size_bytes >= SIZE_1GB:
                        user_level = 3
                    elif file_size_bytes >= SIZE_400MB:
                        user_level = 2
                    elif file_size_bytes >= SIZE_100MB:
                        user_level = 1

                    if user_level > 0:
                        # Define the text for each warning level
                        warning_texts = [
                            "100 MB+: Can be slow on less robust connections.",
                            "400 MB+: Can be slow on typical connections.",
                            "1 GB+  : Can be sluggish even on fast connections."
                        ]

                        # Build the HTML list, highlighting the user's current level
                        warning_list_items = []
                        highlight_index = user_level - 1
                        for i, text in enumerate(warning_texts):
                            if i == highlight_index:
                                item_html = f"<li><b>&gt;&gt; {text} &lt;&lt;</b></li>"
                            else:
                                item_html = f"<li>{text}</li>"
                            warning_list_items.append(item_html)
                        warnings_html = "".join(warning_list_items)

                        # Format the file size for display
                        size_value, size_unit = (file_size_bytes / (1024**3), "GB") if file_size_bytes > SIZE_1GB else (file_size_bytes / (1024**2), "MB")

                        message = (f"Selected vault is <b>{size_value:.2f} {size_unit}</b><br>"
                                   "Larger vaults = longer upload times (plus >% network failures)"
                                   f"<ul>{warnings_html}</ul>"
                                   "If possible, use a smaller, dedicated vault to reduce wait times.")

                        # Create a QMessageBox instance to have more control over its properties.
                        msg_box = QMessageBox(self)
                        msg_box.setIcon(QMessageBox.NoIcon)
                        msg_box.setWindowTitle("Large Vault Warning")
                        # The message contains HTML, so we must use setTextFormat.
                        msg_box.setTextFormat(Qt.RichText)
                        msg_box.setText(message)
                        msg_box.setStandardButtons(QMessageBox.Ok)
                        # Set a minimum width on the label inside the message box to ensure it's wide enough.
                        msg_box.setStyleSheet("QLabel{min-width: 825px; padding-right: 15px;}")
                        msg_box.exec_()

                except OSError:
                    # Fail silently if we can't get the file size for some reason.
                    pass

                # Make the path relative to the home directory for storage in config
                home_dir = os.path.expanduser('~')
                relative_path = os.path.relpath(file_path, home_dir)
                self.vault_path_edit.setText(relative_path)

    def detect_gdrive_paths(self):
        """Attempts to find 'My Drive' directories using 'gio info'."""
        if not shutil.which("gio"):
            QMessageBox.warning(self, "Detection Tool Missing", "'gio' command not found. Please ensure it is installed to use this feature.")
            return

        try:
            uid = os.getuid()
            gvfs_path = f"/run/user/{uid}/gvfs/"

            if not os.path.isdir(gvfs_path):
                QMessageBox.information(self, "Detection Failed", f"The standard GVFS directory was not found at:\n{gvfs_path}")
                return
            
            probe_timeout = 5 # Default - use a reasonable timeout for this detection

            detected_drives = []
            top_level_mounts = [d for d in os.listdir(gvfs_path) if d.startswith('google-drive:')]

            for mount_name in top_level_mounts:
                mount_path = os.path.join(gvfs_path, mount_name)
                if not os.path.isdir(mount_path):
                    continue

                # Extract user email for a more descriptive name
                user_email = "unknown"
                for part in mount_name.split(','):
                    if part.startswith('user='):
                        user_email = part.split('=', 1)[1]
                        break

                for drive_id in os.listdir(mount_path):
                    drive_path = os.path.join(mount_path, drive_id)
                    if not os.path.isdir(drive_path):
                        continue

                    try:
                        command = ["gio", "info", "-a", "standard::display-name", drive_path]
                        process = subprocess.run(
                            command,
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=probe_timeout # Add a timeout for safety
                        )

                        for line in process.stdout.strip().split('\n'):
                            # The attribute key "standard::display-name" contains colons,
                            # so a simple split is not reliable. We split on the full key.
                            key = "standard::display-name:"
                            if key in line:
                                volume_name = line.split(key, 1)[1].strip()
                                if volume_name == "My Drive":
                                    display_name = f"My Drive ({user_email})"
                                    detected_drives.append((display_name, drive_path))
                                break # Found the attribute, move to next drive_id
                    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                        # Silently ignore folders that fail the check
                        continue

            if not detected_drives:
                QMessageBox.information(self, "Detection Complete", "No 'My Drive' folders were found. Please ensure your Google account is mounted in your file manager.")
                return

            if len(detected_drives) == 1:
                # If only one is found, just use it without prompting.
                display_name, full_path = detected_drives[0]
                self.gdrive_path_edit.setText(full_path)
                QMessageBox.information(self, "Drive Detected", f"Automatically selected the detected Google Drive:\n{display_name}")
            else:
                # If multiple are found, prompt the user to choose.
                drive_options = {display: path for display, path in detected_drives}
                selected_display_name, ok = QInputDialog.getItem(
                    self,
                    "Select Google Drive Account",
                    "Multiple 'My Drive' folders detected. Please choose one:",
                    list(drive_options.keys()),
                    0, False # Items are not editable
                )
                if ok and selected_display_name:
                    full_path = drive_options[selected_display_name]
                    self.gdrive_path_edit.setText(full_path)
        except Exception as e:
            QMessageBox.critical(self, "Detection Error", f"An unexpected error occurred during detection:\n{e}")

    def select_gdrive_folder(self):
        """Opens a directory dialog to select the Google Drive backup folder."""
        gdrive_base_path = self.gdrive_path_edit.text().strip()

        if not gdrive_base_path:
            QMessageBox.warning(
                self,
                "Path Missing",
                "Please specify the 'Google Drive Mount Path' before selecting a backup folder."
            )
            return

        current_relative_dir = self.gdrive_dir_edit.text()
        start_dir = os.path.join(gdrive_base_path, current_relative_dir)

        # If the combined path doesn't seem to exist, fall back to the base path.
        if not os.path.isdir(start_dir):
            start_dir = gdrive_base_path

        dialog = QFileDialog(
            self,
            "Select Google Drive Backup Folder",
            start_dir
        )
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.resize(1024, 768)

        if dialog.exec_():
            selected_files = dialog.selectedFiles()
            if selected_files:
                dir_path = selected_files[0]
                # Ensure the selected path is within the base path
                if os.path.commonpath([dir_path, gdrive_base_path]) != gdrive_base_path:
                    QMessageBox.warning(self, "Invalid Directory", "The selected directory must be inside your Google Drive Mount Path.")
                    return

                relative_path = os.path.relpath(dir_path, gdrive_base_path)
                if relative_path == ".": # The root of the base path was selected
                    relative_path = ""
                self.gdrive_dir_edit.setText(relative_path)
