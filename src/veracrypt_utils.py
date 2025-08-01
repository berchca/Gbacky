import os
import subprocess

from command_runner import run_command

def get_mount_point(vault_path, sudo_password=None, log_callback=None):
    """
    Parses 'veracrypt --list' to find the mount point for a given vault.
    Returns the mount point path as a string, or None if not found or an error occurs.
    """
    command = ["veracrypt", "--text", "--list"]
    process = run_command(command, sudo_password=sudo_password, log_callback=log_callback)

    if not process:
        return None

    for line in process.stdout.strip().split('\n'):
        if vault_path in line:
            parts = line.split()
            if len(parts) > 2 and os.path.isdir(parts[-1]):
                return parts[-1]
    return None # Vault found, but no valid mount point in the line

def test_credentials(vault_path, password):
    """
    Tests VeraCrypt credentials by running 'veracrypt --test'.
    Returns a tuple (bool, str) indicating success and a message.
    """
    # This check is now part of the utility, making it self-contained.
    if not os.path.exists(vault_path):
        return False, f"The specified VeraCrypt vault was not found at:\n{vault_path}"

    try:
        command = ["veracrypt", "--text", "--test", "--password", password, "--non-interactive", vault_path]
        process = subprocess.run(command, capture_output=True, text=True, check=False)

        if process.returncode == 0:
            return True, "The password is correct for the specified VeraCrypt vault."
        else:
            error_output = process.stderr.strip()
            return False, f"VeraCrypt test failed.\n\nError: {error_output}"
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, f"An unexpected error occurred while running the test: {e}"