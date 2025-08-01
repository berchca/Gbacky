import os
import json

def is_dev_environment():
    """
    Checks if the application is running in a development environment.
    The check is based on the presence of the 'package_deb.py' script.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.exists(os.path.join(script_dir, 'package_deb.py'))

def get_config_dir():
    """
    Determines the appropriate config directory based on the environment.
    """
    if is_dev_environment():
        return os.path.join(os.path.expanduser('~'), '.config', 'Gbacky-dev')
    else:
        return os.path.join(os.path.expanduser('~'), '.config', 'Gbacky')

def load_config():
    """Loads configuration from the JSON file and validates required keys."""
    config_path = os.path.join(get_config_dir(), 'config.json')
    if not os.path.exists(config_path):
        return None, f"Configuration file not found at '{config_path}'"
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)

        required_keys = [
            "GOOGLE_DRIVE_PATH", "GOOGLE_DRIVE_BACKUP_DIR", "VAULT_PROFILES"
        ]
        for key in required_keys:
            if key not in config:
                return None, f"Missing key '{key}' in configuration file."

        if not isinstance(config["VAULT_PROFILES"], list) or not config["VAULT_PROFILES"]:
            return None, "The 'VAULT_PROFILES' key must be a non-empty list in the configuration file."

        # Validate the first profile to ensure it has the required keys
        first_profile = config["VAULT_PROFILES"][0]
        required_profile_keys = ["ID", "NAME", "VERACRYPT_VAULT", "BACKUP_DIRS"]
        for key in required_profile_keys:
            if key not in first_profile:
                return None, f"The first vault profile is missing the required key: '{key}'"

        return config, None # Return config and no error
    except json.JSONDecodeError as e:
        return None, f"Could not parse configuration file: {e}"
    except IOError as e:
        return None, f"Could not read configuration file: {e}"

def save_config(config_data):
    """Saves the configuration dictionary to the JSON file."""
    config_dir = get_config_dir()
    config_path = os.path.join(config_dir, 'config.json')
    try:
        # Ensure the config directory exists before trying to write to it.
        os.makedirs(config_dir, exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=4)
        return True, None
    except IOError as e:
        return False, f"Could not write to configuration file: {e}"