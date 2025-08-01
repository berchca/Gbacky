import os
import subprocess

from PySide2.QtWidgets import QMessageBox, QInputDialog, QLineEdit
from config_utils import is_dev_environment

def get_sudoers_file_path():
    """
    Determines the appropriate sudoers file path based on the environment.
    """
    if is_dev_environment():
        return '/etc/sudoers.d/veracrypt-backup-script-dev'
    else:
        return '/etc/sudoers.d/veracrypt-backup-script'

def is_password_required():
    """Checks if the passwordless sudo file exists."""
    return not os.path.exists(get_sudoers_file_path())

def verify_sudo_password(password):
    """
    Verifies a sudo password by running a non-destructive command.
    Returns True if the password is correct, False otherwise.
    """
    if not password:
        return False
    try:
        # 'sudo -S -v' updates the user's cached timestamp if the password is correct.
        # It's a safe and standard way to validate a password.
        process = subprocess.run(
            ['sudo', '-S', '-v'],
            input=password, text=True, capture_output=True, check=False
        )
        return process.returncode == 0
    except FileNotFoundError:
        return False # Should not happen if sudo is installed.

def setup_passwordless_sudo(parent):
    """
    Guides the user through creating the passwordless sudo file.
    Returns True on success, False on failure or cancellation.
    """
    msg_box = QMessageBox(parent)
    msg_box.setIcon(QMessageBox.NoIcon)
    msg_box.setWindowTitle("Security Confirmation")
    msg_box.setText(
        "This will create a system file allowing VeraCrypt to be run with sudo privileges without a password.\n\n"
        "This is required for fully automated backups but is a minor security trade-off.\n\n"
        "Do you want to proceed?")
    msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg_box.setDefaultButton(QMessageBox.No)
    msg_box.setStyleSheet("QLabel{min-width: 500px;}")
    reply = msg_box.exec_()
    if reply != QMessageBox.Yes:
        return False

    password, ok = QInputDialog.getText(parent, "Sudo Password", "Please enter your system password to apply this change:", QLineEdit.Password)
    if not ok or not password:
        return False

    sudoers_file = get_sudoers_file_path()
    content = "'%sudo ALL=(root) NOPASSWD: /usr/bin/veracrypt'"
    command_str = f"echo {content} > {sudoers_file} && chmod 0440 {sudoers_file}"
    command = ["sudo", "-S", "sh", "-c", command_str]

    process = subprocess.run(command, input=password, capture_output=True, text=True)

    if process.returncode == 0:
        QMessageBox.information(parent, "Success", "Passwordless sudo rule for VeraCrypt has been created.")
        return True
    else:
        err_box = QMessageBox(parent)
        err_box.setIcon(QMessageBox.NoIcon)
        err_box.setWindowTitle("Failed")
        err_box.setText(f"Could not create sudoers file. Sudo may have rejected the password.\n\nError: {process.stderr}")
        err_box.setStandardButtons(QMessageBox.Ok)
        err_box.setStyleSheet("QLabel{min-width: 500px;}")
        err_box.exec_()
        return False

def remove_passwordless_sudo(parent):
    """
    Guides the user through removing the passwordless sudo file.
    Returns True on success, False on failure or cancellation.
    """
    password, ok = QInputDialog.getText(parent, "Sudo Password", "Please enter your system password to remove the passwordless sudo rule:", QLineEdit.Password)
    if not ok or not password:
        return False

    sudoers_file = get_sudoers_file_path()
    command = ["sudo", "-S", "rm", "-f", sudoers_file]
    process = subprocess.run(command, input=password, capture_output=True, text=True)

    if process.returncode == 0:
        QMessageBox.information(parent, "Success", "Passwordless sudo rule for VeraCrypt has been removed.")
        return True
    else:
        err_box = QMessageBox(parent)
        err_box.setIcon(QMessageBox.NoIcon)
        err_box.setWindowTitle("Failed")
        err_box.setText(f"Could not remove sudoers file. Sudo may have rejected the password.\n\nError: {process.stderr}")
        err_box.setStandardButtons(QMessageBox.Ok)
        err_box.setStyleSheet("QLabel{min-width: 500px;}")
        err_box.exec_()
        return False