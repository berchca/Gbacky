import subprocess
import concurrent.futures

def run_with_timeout(func, args=(), kwargs={}, timeout=30):
    """Runs a function in a thread with a timeout, raising TimeoutError if it hangs."""
    if timeout is None:
        # No timeout - run directly
        return func(*args, **kwargs)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Operation '{func.__name__}' timed out after {timeout}s.")


def run_command(command, sudo_password=None, log_callback=None, output_filter=None):
    """
    A centralized utility for running external commands, especially with sudo.

    Args:
        command (list): The command to run (without sudo).
        sudo_password (str, optional): The sudo password. If an empty string,
            passwordless sudo is assumed. If None, sudo is not used.
        log_callback (callable, optional): A function to call with log messages.
        output_filter (callable, optional): A function to process stdout lines.

    Returns:
        subprocess.CompletedProcess: The process object on success, or None on failure.
    """
    full_command = list(command)
    run_kwargs = {
        'capture_output': True,
        'text': True,
        'check': False  # We check the return code manually to log output on failure
    }

    if sudo_password is not None:  # An empty string means passwordless sudo
        sudo_prefix = ["sudo"]
        if sudo_password:  # A non-empty string is the password
            sudo_prefix.append("-S")
            run_kwargs['input'] = sudo_password
        full_command = sudo_prefix + full_command

    def get_safe_command_str(cmd_list):
        """Creates a log-safe string from a command list, obscuring passwords."""
        log_cmd_str = list(cmd_list)
        try:
            # Find the '--password' argument and replace the value that follows it.
            pw_idx = log_cmd_str.index('--password')
            if pw_idx + 1 < len(log_cmd_str):
                log_cmd_str[pw_idx + 1] = "'********'"
        except ValueError:
            # '--password' not found, so no need to obscure anything.
            pass
        return ' '.join(log_cmd_str)

    # Log the command safely, obscuring any passwords
    if log_callback:
        log_callback(f"-> Running: {get_safe_command_str(full_command)}")

    try:
        process = subprocess.run(full_command, **run_kwargs)

        if process.returncode != 0:
            if log_callback:
                safe_cmd_str = get_safe_command_str(process.args)
                err_msg = (f"ERROR executing command: {safe_cmd_str}\n"
                           f"Return code: {process.returncode}\n"
                           f"Output:\n{process.stdout.strip()}\n"
                           f"Error Output:\n{process.stderr.strip()}")
                log_callback(err_msg)
            return None

        # On success, log stdout (if any), applying the filter.
        if log_callback and process.stdout:
            output_to_log = process.stdout.strip()
            if output_filter:
                processed_lines = []
                for line in output_to_log.split('\n'):
                    if not line:
                        continue
                    # The filter should return the processed line or None to discard it.
                    processed_line = output_filter(line)
                    if processed_line:
                        processed_lines.append(processed_line)
                output_to_log = '\n'.join(processed_lines)

            if output_to_log:
                log_callback(output_to_log)

        # Also log stderr on success, as some tools use it for info (like rsync stats)
        if log_callback and process.stderr:
            log_callback(f"Info (stderr):\n{process.stderr.strip()}")

        return process

    except FileNotFoundError as e:
        if log_callback:
            log_callback(f"ERROR: Command not found or failed to execute: {e}")
        return None