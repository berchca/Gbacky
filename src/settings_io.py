import os
import shutil
from datetime import datetime

from PySide2.QtWidgets import QFileDialog, QMessageBox

from config_utils import get_config_dir

def export_settings_to_file(parent):
    """Exports the current config file to a user-selected location."""
    config_dir = get_config_dir()
    source_path = os.path.join(config_dir, 'config.json')
    if not os.path.exists(source_path):
        QMessageBox.warning(parent, "Export Failed", "No configuration file found to export.")
        return

    documents_dir = os.path.join(os.path.expanduser('~'), 'Documents')
    default_export_path = os.path.join(documents_dir, 'gdbackup_settings.json')

    save_path, _ = QFileDialog.getSaveFileName(
        parent,
        "Export Settings As",
        default_export_path,
        "JSON Files (*.json);;All Files (*)"
    )

    if save_path:
        try:
            shutil.copy2(source_path, save_path)
            QMessageBox.information(parent, "Success", f"Settings successfully exported to:\n{save_path}")
        except (IOError, OSError) as e:
            QMessageBox.critical(parent, "Export Error", f"Could not export settings file.\n\nError: {e}")

def import_settings_from_file(parent):
    """
    Imports a config file, backing up the old one.
    Returns True on success, False otherwise.
    """
    config_dir = get_config_dir()
    current_config_path = os.path.join(config_dir, 'config.json')

    # Only show the warning if a configuration file actually exists.
    if os.path.exists(current_config_path):
        msg_box = QMessageBox(parent)
        msg_box.setIcon(QMessageBox.NoIcon)
        msg_box.setWindowTitle("Import Warning")
        msg_box.setText("Importing settings will overwrite your current configuration.\n\n"
            "Paths and other settings from a different system may not work correctly.\n\n"
            "Do you want to proceed?")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        msg_box.setStyleSheet("QLabel{min-width: 550px;}")
        reply = msg_box.exec_()
        if reply != QMessageBox.Yes:
            return False

    documents_dir = os.path.join(os.path.expanduser('~'), 'Documents')
    import_path, _ = QFileDialog.getOpenFileName(
        parent, "Import Settings File", documents_dir, "JSON Files (*.json);;All Files (*)"
    )

    if import_path:
        # This is the crucial fix: ensure the destination directory exists
        # before trying to back up the old file or copy the new one. This
        # handles the case of importing on a fresh first run.
        os.makedirs(config_dir, exist_ok=True)

        if os.path.exists(current_config_path):
            today_str = datetime.now().strftime('%Y-%m-%d')
            backup_filename = f"config.json.backup.{today_str}"
            backup_path = os.path.join(config_dir, backup_filename)
            try:
                shutil.move(current_config_path, backup_path)
            except (IOError, OSError) as e:
                QMessageBox.critical(parent, "Backup Error", f"Could not back up existing config file.\nImport cancelled.\n\nError: {e}")
                return False

        try:
            shutil.copy2(import_path, current_config_path)
            QMessageBox.information(parent, "Success", "Settings successfully imported. The application will now reload the new settings.")
            return True
        except (IOError, OSError) as e:
            QMessageBox.critical(parent, "Import Error", f"Could not copy the new settings file.\n\nError: {e}")
            return False
    return False