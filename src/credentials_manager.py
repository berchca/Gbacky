import os
import keyring
import keyring.errors

from config_utils import is_dev_environment

def get_service_name():
    """
    Determines the keyring service name based on the environment.
    """
    if is_dev_environment():
        return "gbacky-veracrypt-backup-dev"
    else:
        return "gbacky-veracrypt-backup"

def get_veracrypt_password(vault_path):
    """
    Retrieves the VeraCrypt password from the system's keyring.
    The vault_path is used as the 'username' to allow storing passwords for multiple vaults.
    Returns the password string or None if not found or an error occurs.
    """
    if not vault_path:
        return None
    try:
        return keyring.get_password(get_service_name(), vault_path)
    except keyring.errors.NoKeyringError:
        # This occurs if no supported keyring backend is available.
        return None

def set_veracrypt_password(vault_path, password):
    """
    Saves the VeraCrypt password to the system's keyring.
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    try:
        if not vault_path:
            return False, "Vault path cannot be empty when saving a password."
        keyring.set_password(get_service_name(), vault_path, password)
        return True, None # Success, no error message
    except keyring.errors.NoKeyringError:
        return False, "No system keyring backend found. Please ensure you have a supported keyring service (like GNOME Keyring) installed and running."
    except Exception as e:
        return False, f"An unexpected error occurred while saving the password: {e}"

def delete_veracrypt_password(vault_path):
    """
    Deletes a VeraCrypt password from the system's keyring.
    This is useful when the vault path changes.
    Returns (True, None) on success, or (False, error_message) on failure.
    """
    try:
        if not vault_path:
            return True, None # Nothing to delete
        keyring.delete_password(get_service_name(), vault_path)
        return True, None
    except keyring.errors.PasswordDeleteError:
        # This can happen if the password doesn't exist, which is not a failure in our case.
        return True, None
    except keyring.errors.NoKeyringError:
        return False, "No system keyring backend found."
    except Exception as e:
        return False, f"An unexpected error occurred while deleting the password: {e}"